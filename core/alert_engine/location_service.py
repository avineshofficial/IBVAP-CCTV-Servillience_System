"""
IBVAP — Live Real-Time Location Service
==========================================
Resolves the system's current GPS coordinates with priority chain:
1. Browser Geolocation (pushed from dashboard via POST /api/v1/system/live-location)
2. Windows OS Native Location Service (PowerShell GeoCoordinateWatcher)
3. IP Geolocation (ipinfo.io with 5-minute TTL cache)
4. Offline fallback ("Unavailable")

ZERO hardcoded coordinates — every value comes from a live source.
"""

import time
import logging
import subprocess
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class LiveLocationService:
    """Singleton service for real-time GPS coordinate resolution."""

    def __init__(self):
        self._lock = threading.Lock()
        # Browser GPS cache (highest priority)
        self._browser_gps: Optional[dict] = None  # {lat, lng, accuracy, timestamp}
        # Windows OS location cache
        self._os_gps: Optional[dict] = None
        self._os_gps_last_attempt: float = 0.0
        # IP geolocation cache (5-min TTL)
        self._ip_geo: Optional[dict] = None
        self._ip_geo_expires: float = 0.0
        self._IP_GEO_TTL = 300.0  # 5 minutes

    def update_browser_gps(self, lat: float, lng: float, accuracy: float = 0.0) -> None:
        """Store the latest browser-pushed GPS coordinates."""
        with self._lock:
            self._browser_gps = {
                "lat": lat,
                "lng": lng,
                "accuracy": accuracy,
                "timestamp": time.time(),
                "source": "browser_gps",
            }
            logger.info(f"[Location] Browser GPS updated: {lat:.6f}, {lng:.6f} (±{accuracy:.0f}m)")

    def get_browser_gps(self) -> Optional[dict]:
        """Return cached browser GPS if fresh (< 5 minutes old)."""
        with self._lock:
            if self._browser_gps and (time.time() - self._browser_gps["timestamp"]) < 300:
                return self._browser_gps.copy()
        return None

    def _query_windows_location(self) -> Optional[dict]:
        """Query Windows OS native location service via PowerShell (3s timeout)."""
        # Rate limit: try at most once every 30 seconds
        if time.time() - self._os_gps_last_attempt < 30.0:
            return self._os_gps
        self._os_gps_last_attempt = time.time()

        try:
            ps_script = (
                'Add-Type -AssemblyName System.Device; '
                '$w = New-Object System.Device.Location.GeoCoordinateWatcher; '
                '$w.Start(); '
                '$timeout = 3; $elapsed = 0; '
                'while ($w.Status -ne "Ready" -and $elapsed -lt $timeout) { '
                'Start-Sleep -Milliseconds 500; $elapsed += 0.5 }; '
                'if ($w.Status -eq "Ready") { '
                '$c = $w.Position.Location; '
                'Write-Output "$($c.Latitude),$($c.Longitude),$($c.HorizontalAccuracy)" '
                '} else { Write-Output "UNAVAILABLE" }; '
                '$w.Stop()'
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout.strip()
            if output and output != "UNAVAILABLE":
                parts = output.split(",")
                if len(parts) >= 2:
                    lat, lng = float(parts[0]), float(parts[1])
                    accuracy = float(parts[2]) if len(parts) > 2 else 0.0
                    if lat != 0.0 or lng != 0.0:
                        self._os_gps = {
                            "lat": lat, "lng": lng, "accuracy": accuracy,
                            "timestamp": time.time(), "source": "windows_os",
                        }
                        logger.info(f"[Location] Windows OS location: {lat:.6f}, {lng:.6f}")
                        return self._os_gps
        except Exception as e:
            logger.debug(f"[Location] Windows location service error: {e}")
        return None

    def _query_ip_geolocation(self) -> Optional[dict]:
        """Fetch live coordinates from IP geolocation API (cached 5 min)."""
        if self._ip_geo and time.time() < self._ip_geo_expires:
            return self._ip_geo

        try:
            import httpx
            resp = httpx.get("https://ipinfo.io/json", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                loc = data.get("loc", "")
                city = data.get("city", "")
                region = data.get("region", "")
                if loc and "," in loc:
                    lat, lng = loc.split(",")
                    location_label = f"{city}, {region}" if city else "IP-based"
                    self._ip_geo = {
                        "lat": float(lat), "lng": float(lng), "accuracy": 5000.0,
                        "timestamp": time.time(), "source": "ip_geolocation",
                        "label": location_label,
                    }
                    self._ip_geo_expires = time.time() + self._IP_GEO_TTL
                    logger.info(f"[Location] IP geolocation: {lat}, {lng} ({location_label})")
                    return self._ip_geo
        except Exception as e:
            logger.debug(f"[Location] IP geolocation error: {e}")
        return None

    def get_live_location(self) -> dict:
        """
        Resolve the current live location using the priority chain.
        Returns dict with lat, lng, accuracy, source, label.
        Returns unavailable status if all sources fail.
        """
        # Priority 1: Browser GPS
        browser = self.get_browser_gps()
        if browser:
            browser["label"] = "Live Browser GPS"
            return browser

        # Priority 2: Windows OS location
        os_loc = self._query_windows_location()
        if os_loc:
            os_loc["label"] = "Windows Location Service"
            return os_loc

        # Priority 3: IP Geolocation
        ip_loc = self._query_ip_geolocation()
        if ip_loc:
            return ip_loc

        # Offline: no location available
        return {
            "lat": None, "lng": None, "accuracy": None,
            "timestamp": time.time(), "source": "unavailable",
            "label": "Real-Time Location Unavailable (Offline)",
        }


# Singleton
_location_service: Optional[LiveLocationService] = None


def get_location_service() -> LiveLocationService:
    """Get or instantiate global LiveLocationService singleton."""
    global _location_service
    if _location_service is None:
        _location_service = LiveLocationService()
    return _location_service
