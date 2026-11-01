"""UDP Network Discovery for finding devices"""

import socket
import threading
import time
import json
from typing import Optional, Callable, Dict, List
from datetime import datetime, timedelta

from ..models.device import Device
from .netio import open_discovery_socket
from .protocol import Protocol, MessageType
from ..utils.logger import get_logger
from ..utils.config import get_config
from ..utils import netif
from ..utils.helpers import get_hostname, get_local_ip
from ..utils.ports import DEFAULT_DISCOVERY_PORT, DEFAULT_TRANSFER_PORT
from ..models.database import get_database


class NetworkDiscovery:
    """Network discovery service using UDP broadcast"""
    
    BROADCAST_PORT = DEFAULT_DISCOVERY_PORT
    BROADCAST_INTERVAL = 5  # seconds
    DEVICE_TIMEOUT = 15  # seconds

    # Kimliksiz UDP keşfiyle sınırsız Device üretilmesini sınırla
    MAX_DEVICES = 512
    MAX_DEVICES_PER_IP = 8
    MAX_TEXT_LENGTH = 64

    def __init__(self):
        """Initialize network discovery"""
        self.config = get_config()
        self.logger = get_logger()
        
        self.running = False
        self.broadcast_thread: Optional[threading.Thread] = None
        self.listen_thread: Optional[threading.Thread] = None
        
        self.devices: Dict[str, Device] = {}  # key: "ip:port"
        self.devices_lock = threading.Lock()  # Thread-safe access to devices dict
        self.cleanup_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self.on_device_found: Optional[Callable] = None
        self.on_device_lost: Optional[Callable] = None
        
        # Socket
        self.sock: Optional[socket.socket] = None
        self._broadcast_event = threading.Event()

        import uuid
        self._instance_id: str = str(uuid.uuid4())
        try:
            from .crypto import get_local_fingerprint
            self._local_fingerprint: Optional[str] = get_local_fingerprint()
        except Exception:
            self._local_fingerprint = None

        # Yerel IP kümesi — kendi yayınlarımızı eleme + tüm arayüzlere yayın için
        self._local_ips: set = self._collect_local_ips()

        # Kullanıcının sildiği cihazlar — yayın gelse bile yeniden eklenmez
        self._blocked: set = set()
    
    def start(self):
        """Start network discovery"""
        if self.running:
            return
        
        # Keşif portunu bağla (önce varsayılan, gerekirse yedek)
        candidates = [self.BROADCAST_PORT, 38522, 38523]
        self.sock = None

        for candidate_port in candidates:
            try:
                self.sock = self._open_socket(candidate_port)
                self.BROADCAST_PORT = candidate_port
                break
            except Exception as e:
                self.logger.warning(f"Port {candidate_port} keşif için bağlanamadı: {e}")

        if not self.sock:
            self.logger.error("Ağ keşfi başlatılamadı: Keşif portu bağlanamadı.")
            self.running = False
            return

        try:
            self.running = True
            self._broadcast_event.clear()
            
            # Start broadcast thread
            self.broadcast_thread = threading.Thread(target=self._broadcast_presence, daemon=True)
            self.broadcast_thread.start()
            
            # Start listen thread
            self.listen_thread = threading.Thread(target=self._listen_broadcasts, daemon=True)
            self.listen_thread.start()
            
            # Start cleanup thread
            self.cleanup_thread = threading.Thread(target=self._cleanup_offline_devices, daemon=True)
            self.cleanup_thread.start()
            
            self.logger.info(f"Network discovery started on port {self.BROADCAST_PORT}")
            
        except Exception as e:
            self.logger.error(f"Failed to start network discovery threads: {e}")
            self.running = False
    
    def _open_socket(self, port: int, host: str = '') -> socket.socket:
        """Keşif UDP soketini güvenli seçeneklerle açıp bağlar (hata olursa soketi kapatıp fırlatır).

        Üç platformda da ÖZEL bağlama (Windows: SO_EXCLUSIVEADDRUSE; Linux/macOS: REUSEADDR/REUSEPORT
        yok): ikinci yerel örnek EADDRINUSE alıp yedek porta (38522/38523) geçer, yanıtlar sessizce
        bölünmez. Ayrıntı için bkz. `netio.open_discovery_socket`.
        """
        return open_discovery_socket(port, host)

    def stop(self):
        """Stop network discovery"""
        if not self.running:
            return
        self.running = False
        if hasattr(self, '_broadcast_event'):
            self._broadcast_event.set()
        
        # Ağdaki diğer cihazlara hemen çevrimdışı olduğumuzu bildir
        self._send_goodbye()
        
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        
        # Wait for threads
        if self.broadcast_thread:
            self.broadcast_thread.join(timeout=2)
        if self.listen_thread:
            self.listen_thread.join(timeout=2)
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=2)
        
        self.logger.info("Network discovery stopped")

    def _send_goodbye(self):
        """Uygulama kapanırken ağdaki cihazlara veda paketi gönder."""
        if not self.sock:
            return
        try:
            device_name = self.config.get('general', 'device_name', get_hostname())
            hostname = get_hostname()
            port = self.config.get('transfer', 'port', DEFAULT_TRANSFER_PORT)
            msg = Protocol.create_goodbye_message(
                device_name, hostname, port, instance_id=self._instance_id
            )
            data = json.dumps(msg).encode('utf-8')
            for target in self._broadcast_targets():
                for port in self._broadcast_ports():
                    try:
                        self.sock.sendto(data, (target, port))
                    except Exception:
                        pass
        except Exception:
            pass

    def broadcast_now(self):
        """Hemen bir keşif yayını tetikle (kullanıcı yenilediğinde vb.)"""
        if self.running and self.sock:
            self._send_presence_packet()
        if hasattr(self, '_broadcast_event'):
            self._broadcast_event.set()
    
    def _collect_local_ips(self) -> set:
        """Tüm yerel IPv4 adreslerini topla (çoklu NIC/VPN için)."""
        ips: set = set()
        try:
            # Arayüz sayımı (Linux'ta gethostname() çoğu zaman yalnızca 127.0.1.1 verir)
            ips.update(netif.local_ipv4_addresses(netif.list_ipv4_interfaces()))
        except Exception:
            pass
        try:
            for family, _, _, _, sockaddr in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET
            ):
                if family == socket.AF_INET and sockaddr:
                    ips.add(sockaddr[0])
        except Exception:
            pass
        try:
            _, _, host_ips = socket.gethostbyname_ex(socket.gethostname())
            ips.update(host_ips)
        except Exception:
            pass
        try:
            ips.add(get_local_ip())
        except Exception:
            pass
        ips.discard("")
        return ips

    def _is_self(self, data: dict, sender_ip: str) -> bool:
        """Kendi cihazımıza ait paketleri tespit et (kendi kendini görme hatasını önler)."""
        if sender_ip in self._local_ips:
            return True
        if self._instance_id and data.get('instance_id') == self._instance_id:
            self._local_ips.add(sender_ip)
            return True
        if self._local_fingerprint and data.get('fingerprint') == self._local_fingerprint:
            self._local_ips.add(sender_ip)
            return True
        local_hostname = get_hostname()
        local_dev_name = self.config.get('general', 'device_name', local_hostname)
        if data.get('hostname') == local_hostname and data.get('device_name') == local_dev_name:
            self._local_ips.add(sender_ip)
            return True
        return False

    def _broadcast_targets(self) -> list:
        """Genel yayın + her uygun arayüzün alt-ağına yönlendirilmiş yayın (gerçek maskeyle).

        Linux/macOS'ta 255.255.255.255 yalnızca varsayılan rotanın arayüzünden çıkar; çoklu
        NIC/VPN'de diğer arayüzler yönlendirilmiş adresle kapsanır. Noktadan noktaya (VPN tüneli)
        ve konteyner köprüleri atlanır (bkz. `utils.netif`).
        """
        return netif.broadcast_targets(netif.list_ipv4_interfaces(), fallback_ips=self._local_ips)

    def _broadcast_ports(self) -> list:
        """Yayının gideceği UDP portları.

        Yedek porta geçildiyse (varsayılan port başka bir yerel örnekte) yayın aynı zamanda
        varsayılan porta da gider: o örnek bizi duyar ve `discovery_port` alanındaki yedek portumuza
        yanıt verir; aksi halde iki yerel örnek birbirini hiç görmezdi.
        """
        ports = [self.BROADCAST_PORT]
        if self.BROADCAST_PORT != DEFAULT_DISCOVERY_PORT:
            ports.append(DEFAULT_DISCOVERY_PORT)
        return ports

    def _send_presence_packet(self):
        """Send a single presence broadcast across all network targets"""
        if not self.running or not self.sock:
            return
        try:
            self._local_ips = self._collect_local_ips()
            device_name = self.config.get('general', 'device_name', get_hostname())
            hostname = get_hostname()
            port = self.config.get('transfer', 'port', DEFAULT_TRANSFER_PORT)

            message = Protocol.create_discover_message(
                device_name, hostname, port,
                instance_id=self._instance_id,
                fingerprint=self._local_fingerprint,
                discovery_port=self.BROADCAST_PORT
            )
            data = json.dumps(message).encode('utf-8')

            for target in self._broadcast_targets():
                for port_number in self._broadcast_ports():
                    try:
                        self.sock.sendto(data, (target, port_number))
                    except Exception:
                        continue
        except Exception as e:
            if self.running:
                self.logger.error(f"Error sending presence packet: {e}")

    def _broadcast_presence(self):
        """Broadcast presence to network with startup burst for instant discovery"""
        # Açılışta 150ms arayla çift paket gönder (Wi-Fi paket kaybını önler)
        self._send_presence_packet()
        time.sleep(0.15)
        self._send_presence_packet()

        while self.running:
            try:
                self._broadcast_event.wait(timeout=self.BROADCAST_INTERVAL)
                self._broadcast_event.clear()
                if not self.running:
                    break

                self._send_presence_packet()
            except Exception as e:
                if self.running:
                    self.logger.error(f"Error broadcasting presence: {e}")
    
    def _listen_broadcasts(self):
        """Listen for broadcasts from other devices"""
        while self.running:
            try:
                if not self.sock:
                    time.sleep(0.5)
                    continue

                data, address = self.sock.recvfrom(4096)

                # Kendi yayınlarımızı yoksay (önbellekten hızlı kontrol)
                if address[0] in self._local_ips:
                    continue
                
                # Parse message
                try:
                    message = json.loads(data.decode('utf-8'))
                    msg_type, msg_data = Protocol.parse_message(message)

                    # Kendi cihazımıza ait paketleri detaylı kontrol et ve ele
                    if self._is_self(msg_data, address[0]):
                        continue
                    
                    if msg_type == MessageType.DISCOVER:
                        self._handle_discover(msg_data, address[0], address[1])
                    elif msg_type == MessageType.DISCOVER_RESPONSE:
                        self._handle_discover_response(msg_data, address[0])
                    elif msg_type == MessageType.GOODBYE:
                        self._handle_goodbye(msg_data, address[0])
                        
                except ValueError:
                    # JSONDecodeError ve UTF-8 çözme hataları (kimliksiz paketler günlüğü doldurmasın)
                    continue

            except socket.timeout:
                continue
            except ConnectionResetError:
                # Eşin kapanması (ICMP) dinlemeyi bozmamalı; asıl önlem SIO_UDP_CONNRESET
                continue
            except Exception as e:
                if self.running:
                    self.logger.error(f"Error listening for broadcasts: {e}")
    
    @staticmethod
    def _valid_port(value) -> Optional[int]:
        """1..65535 aralığında gerçek bir tamsayı portu döndürür, aksi halde None."""
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 1 <= value <= 65535 else None

    def _clean_text(self, value, default: str = 'Unknown') -> str:
        """Ağdan gelen ad/hostname: yalnızca metin, kontrol karakterleri atılır, uzunluk sınırlı."""
        if not isinstance(value, str):
            return default
        cleaned = ''.join(ch for ch in value if ch.isprintable()).strip()
        return cleaned[:self.MAX_TEXT_LENGTH] or default

    def _can_add_device(self, ip: str) -> bool:
        """Yeni (kimliksiz) cihaz eklenebilir mi: toplam ve IP başına üst sınır. devices_lock altında çağrılır."""
        if len(self.devices) >= self.MAX_DEVICES:
            return False
        prefix = f"{ip}:"
        same_ip = sum(1 for key in self.devices if key.startswith(prefix))
        return same_ip < self.MAX_DEVICES_PER_IP

    def _handle_discover(self, data: dict, ip: str, sender_port: int = 0):
        """Handle discovery message"""
        device_name = self._clean_text(data.get('device_name'))
        hostname = self._clean_text(data.get('hostname'))
        port = self._valid_port(data.get('port', DEFAULT_TRANSFER_PORT))
        if port is None:
            self.logger.debug(f"Geçersiz port içeren keşif paketi yok sayıldı ({ip})")
            return
        disc_port = self._valid_port(data.get('discovery_port'))

        device_key = f"{ip}:{port}"

        # Kullanıcının sildiği cihazı yayınla geri getirme
        with self.devices_lock:
            if device_key in self._blocked:
                return
            if device_key in self.devices:
                device = self.devices[device_key]
                was_offline = not device.is_online
                device.update_last_seen()
                if was_offline and self.on_device_found:
                    self.on_device_found(device)

                # Ensure favorite status is loaded from database
                if not hasattr(device, '_favorite_loaded') or not device._favorite_loaded:
                    try:
                        db = get_database()
                        saved_device = db.get_device(ip, port)
                        if saved_device:
                            device.is_favorite = bool(saved_device.get('is_favorite', 0))
                            device.custom_name = saved_device.get('custom_name')
                        device._favorite_loaded = True
                    except Exception as e:
                        self.logger.error(f"Failed to load device from database: {e}")
            else:
                if not self._can_add_device(ip):
                    self.logger.warning(f"Cihaz sınırı aşıldı; {ip}:{port} keşfi yok sayıldı")
                    return

                # Create new device
                device = Device(ip, port, device_name, hostname)

                # Load favorite status from database
                try:
                    db = get_database()
                    saved_device = db.get_device(ip, port)
                    if saved_device:
                        device.is_favorite = bool(saved_device.get('is_favorite', 0))
                        device.custom_name = saved_device.get('custom_name')
                    device._favorite_loaded = True
                except Exception as e:
                    self.logger.error(f"Failed to load device from database: {e}")
                    device._favorite_loaded = True

                self.devices[device_key] = device

                self.logger.info(f"Device discovered: {device_name} at {ip}")
                
                # Notify callback (outside lock to avoid deadlock)
                if self.on_device_found:
                    self.on_device_found(device)
                
        # Send response (outside lock)
        self._send_discover_response(ip, target_disc_port=disc_port, sender_udp_port=sender_port)
    
    def _handle_discover_response(self, data: dict, ip: str):
        """Handle discovery response"""
        device_name = self._clean_text(data.get('device_name'))
        hostname = self._clean_text(data.get('hostname'))
        port = self._valid_port(data.get('port', DEFAULT_TRANSFER_PORT))
        if port is None:
            self.logger.debug(f"Geçersiz port içeren keşif yanıtı yok sayıldı ({ip})")
            return

        device_key = f"{ip}:{port}"

        # Kullanıcının sildiği cihazı yanıtla geri getirme
        with self.devices_lock:
            if device_key in self._blocked:
                return
            if device_key not in self.devices:
                if not self._can_add_device(ip):
                    self.logger.warning(f"Cihaz sınırı aşıldı; {ip}:{port} yanıtı yok sayıldı")
                    return
                device = Device(ip, port, device_name, hostname)
                
                # Load favorite status from database
                try:
                    db = get_database()
                    saved_device = db.get_device(ip, port)
                    if saved_device:
                        device.is_favorite = bool(saved_device.get('is_favorite', 0))
                        device.custom_name = saved_device.get('custom_name')
                    device._favorite_loaded = True
                except Exception as e:
                    self.logger.error(f"Failed to load device from database: {e}")
                    device._favorite_loaded = True
                
                self.devices[device_key] = device
                
                self.logger.info(f"Device found via response: {device_name} at {ip}")
                
                # Notify callback (outside lock)
                if self.on_device_found:
                    self.on_device_found(device)
            else:
                device = self.devices[device_key]
                was_offline = not device.is_online
                if device_name and device_name != "Unknown":
                    device.name = device_name
                if hostname and hostname != "Unknown":
                    device.hostname = hostname
                device.update_last_seen()
                if was_offline and self.on_device_found:
                    self.on_device_found(device)

    def _handle_goodbye(self, data: dict, ip: str):
        """Handle goodbye message from disconnecting device"""
        port = self._valid_port(data.get('port', DEFAULT_TRANSFER_PORT))
        if port is None:
            return
        device_key = f"{ip}:{port}"
        with self.devices_lock:
            if device_key in self.devices:
                device = self.devices[device_key]
                if device.is_online:
                    device.mark_offline()
                    self.logger.info(f"Cihaz ayrıldı (veda): {device.name} ({ip})")
                    if self.on_device_lost:
                        self.on_device_lost(device)

    def _send_discover_response(self, target_ip: str, target_disc_port: Optional[int] = None, sender_udp_port: int = 0):
        """Send discovery response to specific device"""
        if not self.sock:
            return
        try:
            device_name = self.config.get('general', 'device_name', get_hostname())
            hostname = get_hostname()
            port = self.config.get('transfer', 'port', DEFAULT_TRANSFER_PORT)
            
            message = Protocol.create_discover_response(
                device_name, hostname, port,
                instance_id=self._instance_id,
                fingerprint=self._local_fingerprint,
                discovery_port=self.BROADCAST_PORT
            )
            data = json.dumps(message).encode('utf-8')
            
            dest_port = target_disc_port or self.BROADCAST_PORT
            self.sock.sendto(data, (target_ip, dest_port))
            if sender_udp_port and sender_udp_port > 1024 and sender_udp_port != dest_port:
                try:
                    self.sock.sendto(data, (target_ip, sender_udp_port))
                except Exception:
                    pass
            
        except Exception as e:
            self.logger.error(f"Error sending discovery response: {e}")
    
    def _cleanup_offline_devices(self):
        """Remove devices that haven't been seen recently"""
        while self.running:
            try:
                now = datetime.now()
                timeout_threshold = now - timedelta(seconds=self.DEVICE_TIMEOUT)
                
                devices_to_remove = []
                
                # Thread-safe iteration
                with self.devices_lock:
                    devices_copy = list(self.devices.items())
                
                for device_key, device in devices_copy:
                    # Elle eklenenler yayın yapmaz; yoklama ile yaşar, zaman aşımına uğramaz
                    if getattr(device, 'is_manual', False):
                        continue
                    if device.last_seen < timeout_threshold and device.is_online:
                        device.mark_offline()
                        self.logger.info(f"Device offline: {device.name}")
                        
                        if self.on_device_lost:
                            self.on_device_lost(device)
                
                time.sleep(5)
                
            except Exception as e:
                if self.running:
                    self.logger.error(f"Error cleaning up devices: {e}")
    
    def get_devices(self) -> Dict[str, Device]:
        """Get dictionary of all discovered devices (thread-safe, excluding self)"""
        with self.devices_lock:
            local_hostname = get_hostname()
            local_dev_name = self.config.get('general', 'device_name', local_hostname)
            return {
                k: d for k, d in self.devices.items()
                if d.ip not in self._local_ips
                and not (d.hostname == local_hostname and d.name == local_dev_name)
            }
    
    def get_online_devices(self) -> List[Device]:
        """Get list of online devices (thread-safe, excluding self)"""
        with self.devices_lock:
            local_hostname = get_hostname()
            local_dev_name = self.config.get('general', 'device_name', local_hostname)
            return [
                d for d in self.devices.values()
                if d.is_online
                and d.ip not in self._local_ips
                and not (d.hostname == local_hostname and d.name == local_dev_name)
            ]
    
    def get_device(self, ip: str, port: int) -> Optional[Device]:
        """Get device by IP and port (thread-safe)"""
        device_key = f"{ip}:{port}"
        with self.devices_lock:
            return self.devices.get(device_key)
    
    def probe_device(self, ip: str, port: int, timeout: float = 3.0) -> bool:
        """TCP el sıkışması yapmadan porta ulaşılabilirliği yokla (yayınsız ağlar için)."""
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except Exception:
            return False

    def forget_device(self, ip: str, port: int):
        """Cihazı listeden çıkar ve yayınla geri gelmesini engelle."""
        device_key = f"{ip}:{port}"
        with self.devices_lock:
            self._blocked.add(device_key)
            self.devices.pop(device_key, None)
        self.logger.info(f"Device forgotten: {device_key}")

    def add_manual_device(self, ip: str, port: int, name: str) -> Device:
        """Manually add a device (thread-safe)"""
        device_key = f"{ip}:{port}"

        with self.devices_lock:
            self._blocked.discard(device_key)
            if device_key in self.devices:
                device = self.devices[device_key]
                device.is_manual = True
                if name and name != ip:
                    device.custom_name = name
                return device

            device = Device(ip, port, name, name)
            if name and name != ip:
                device.custom_name = name
            device.is_online = False  # Yoklama (probe) başarılı olunca çevrimiçi olur
            device.is_manual = True
            self.devices[device_key] = device

        self.logger.info(f"Manual device added: {name} at {ip}")

        return device

    def solicit_device(self, ip: str, timeout: float = 2.0) -> Optional[Device]:
        """Hedefe tek noktaya (unicast) keşif paketi gönder, yanıtı bekle.

        Karşı taraf yedek porta geçmiş olsa bile yanıt gerçek transfer
        portunu içerir; böylece portu tahmin etmeye gerek kalmaz.
        """
        if not self.running or self.sock is None:
            return None
        try:
            device_name = self.config.get('general', 'device_name', get_hostname())
            hostname = get_hostname()
            port = self.config.get('transfer', 'port', DEFAULT_TRANSFER_PORT)
            message = Protocol.create_discover_message(
                device_name, hostname, port,
                instance_id=self._instance_id,
                fingerprint=self._local_fingerprint,
                discovery_port=self.BROADCAST_PORT
            )
            data = json.dumps(message).encode('utf-8')
            for port_number in self._broadcast_ports():
                self.sock.sendto(data, (ip, port_number))
        except Exception as e:
            self.logger.warning(f"Discover solicitation failed for {ip}: {e}")
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.devices_lock:
                for key, dev in self.devices.items():
                    if key.split(':')[0] == ip and dev.is_online:
                        return dev
            time.sleep(0.2)
        return None

    def probe_manual_device(
        self,
        ip: str,
        port: int,
        timeout: float = 4.0,
        display_name: str | None = None,
    ) -> Optional[Device]:
        """Elle eklenen cihazı bul; önce keşif yanıtı, sonra TCP yoklaması dene."""
        device = self.add_manual_device(ip, port, display_name or ip)
        found = self.solicit_device(ip, timeout=min(2.0, timeout))
        if found is not None:
            found.is_manual = True
            if display_name and display_name != ip:
                found.custom_name = display_name
            if found.port != port:
                stale_key = f"{ip}:{port}"
                with self.devices_lock:
                    self.devices.pop(stale_key, None)
            self.logger.info(f"Manual device answered discovery: {found.full_address}")
            return found
        if self.probe_device(ip, port, timeout):
            device.update_last_seen()
            device.name = device.name or ip
            if display_name and display_name != ip:
                device.custom_name = display_name
            self.logger.info(f"Manual device reachable: {ip}:{port}")
            return device
        self.logger.warning(f"Manual device unreachable: {ip}:{port}")
        return None

    def get_manual_devices(self) -> List[Device]:
        """Elle eklenen cihazlar (thread-safe)."""
        with self.devices_lock:
            return [d for d in self.devices.values() if getattr(d, 'is_manual', False)]

    def reprobe_manual_devices(self, timeout: float = 3.0):
        """Elle eklenenleri yeniden yokla; durum değişimlerini callback ile bildir."""
        for device in self.get_manual_devices():
            was_online = device.is_online
            try:
                reachable = self.probe_device(device.ip, device.port, timeout)
            except Exception:
                reachable = False
            if reachable:
                device.update_last_seen()
                if not was_online and self.on_device_found:
                    self.on_device_found(device)
            elif was_online:
                device.mark_offline()
                if self.on_device_lost:
                    self.on_device_lost(device)
    
    def remove_device(self, ip: str, port: int):
        """Remove a device (thread-safe)"""
        device_key = f"{ip}:{port}"
        with self.devices_lock:
            if device_key in self.devices:
                device = self.devices[device_key]
                del self.devices[device_key]
                self.logger.info(f"Device removed: {device.name}")

