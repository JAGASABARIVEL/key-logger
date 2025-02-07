import sys
import json
import re
import time
import logging
import threading
import platform
from datetime import datetime
import subprocess
import traceback
import argparse

import requests
from pynput import keyboard
from browser_history import get_history
from win32gui import GetForegroundWindow, GetWindowText

import config

logging.basicConfig(level=logging.INFO)


parser = argparse.ArgumentParser()
parser.add_argument("--host", help="Host IP to which the stats to be sent")
parser.add_argument("--interval", help="Interval to let the system know how frequent the stats has to be sent / persisted")
parser.add_argument("--idletime", help="Threshold to calculate the idle time")

class BrowserLogger:
    def __init__(self, unproductive_urls):
        self.unproductive_urls = unproductive_urls
        self.browser_time = {}  # Real-time tracking for the current day
        self.browser_history = {}  # Persistent history grouped by date

    def fetch_browser_history(self):
        """
        Fetch browser history using browser_history package.
        """
        try:
            outputs = get_history()
            history = outputs.histories  # List of (timestamp, URL, title)
            return history
        except Exception as e:
            logging.error(f"Error fetching browser history: {e}")
            return []

    def log_browser_activity(self):
        """
        Log time spent on different URLs grouped by date.
        """
        try:
            history = self.fetch_browser_history()
            today = str(datetime.now().date())

            # Initialize today's entry if not present
            if today not in self.browser_time:
                self.browser_time[today] = {}

            for entry in history:
                timestamp, url, title = entry
                entry_date = str(timestamp.date())

                # Group URLs by their date
                if entry_date not in self.browser_history:
                    self.browser_history[entry_date] = {}

                domain = url.split('/')[2] if '//' in url else url

                # Update history for the specific date
                if domain not in self.browser_history[entry_date]:
                    self.browser_history[entry_date][domain] = {"time_spent": 0, "visits": 0}

                self.browser_history[entry_date][domain]["time_spent"] += 1  # Placeholder
                self.browser_history[entry_date][domain]["visits"] += 1

                # Update real-time tracking for today
                if entry_date == today:
                    if domain not in self.browser_time[today]:
                        self.browser_time[today][domain] = {"time_spent": 0, "visits": 0}
                    self.browser_time[today][domain]["time_spent"] += 1
                    self.browser_time[today][domain]["visits"] += 1

            return self.browser_time
        except Exception as e:
            logging.error(f"Error logging browser activity: {e}")
            return {}



class ApplicationLogger:
    def __init__(self):
        self.app_time = {}

    @staticmethod
    def get_active_window():
        try:
            return GetWindowText(GetForegroundWindow())
        except Exception as e:
            logging.error(f"Error getting active window: {e}")
            return "Unknown"

    def log_active_app(self):
        active_window = self.get_active_window()
        self.app_time[active_window] = self.app_time.get(active_window, 0) + 1
        return self.app_time


class IdleTimeLogger:
    def __init__(self, idle_threshold=300):
        self.idle_threshold = idle_threshold
        self.total_idle_time = 0
        self.current_logged_time = 0

    def get_idle_time(self):
        """
        Platform-specific logic to calculate idle time.
        """
        if platform.system() == "Windows":
            import ctypes
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return millis / 1000.0
        else:
            raise NotImplementedError("Idle time tracking is not implemented for this OS.")

    def check_idle(self):
        """
        Check if the system has been idle for longer than the threshold.
        """
        try:
            idle_time = self.get_idle_time()
            if idle_time >= self.idle_threshold:
                print("idle_time ", idle_time)
                self.total_idle_time += (idle_time - self.current_logged_time)
                self.current_logged_time = idle_time
            else:
                self.current_logged_time = 0
            return self.total_idle_time
        except Exception as e:
            logging.error(f"Error calculating idle time: {e}")
            return 0


class KeyboardLogger:
    def __init__(self, application_logger):
        self.key_data = {}  # To store keys per application or URL
        self.application_logger = application_logger

    def track_keys(self):
        def on_press(key):
            try:
                # Determine the active application
                active_window = self.application_logger.get_active_window()
                if active_window not in self.key_data:
                    self.key_data[active_window] = []

                # Record the key pressed
                key_char = key.char if hasattr(key, 'char') else str(key)
                self.key_data[active_window].append(key_char)
            except Exception as e:
                logging.error(f"Error tracking key: {e}")

        listener = keyboard.Listener(on_press=on_press)
        listener.start()
        listener.join()  # Keep this thread alive.



class ProductivityTracker:
    def __init__(self, host="127.0.0.1", log_interval=300, idletime=300): # 5 mins once we log
        self.host = host
        self._loaded = False
        self.log_interval = log_interval
        self.uuid = self.get_system_uuid()
        self.unproductive_urls = ["facebook.com", "youtube.com", "instagram.com", "reddit.com"]
        self.browser_logger = BrowserLogger(self.unproductive_urls)
        self.application_logger = ApplicationLogger()
        self.idle_logger = IdleTimeLogger(idle_threshold=idletime) # 2 mins is the threshold for inactive time
        self.keyboard_logger = KeyboardLogger(self.application_logger)
        self.load_logs()
        self.threads = []
        # Update idle time
        if self.loaded and self.logs.get("day_logs", {}).get(self.today):
            self.idle_logger.total_idle_time = self.logs["day_logs"][self.today]["idle_time"]
            self.loaded = False

    @property
    def loaded(self):
        return self._loaded

    @loaded.setter
    def loaded(self, flag):
        self._loaded = flag
    
    @property
    def headers(self):
        return {
            "Content-Type": "application/json"
        }

    def get_windows_mac():
        import subprocess

    def get_system_uuid(self):
        try:
            pattern = r"(([\da-zA-z]+\-)+([\da-zA-z])+)"
            # Use WMIC command to get the UUID
            output = subprocess.check_output(
                "wmic csproduct get uuid", shell=True, universal_newlines=True
            )
            uuid = re.search(pattern, output).groups()[0]  # Extract the UUID from the output
            return uuid
        except Exception as e:
            raise e

    def load_logs(self):
        try:
            with open("productivity_logs.json", "r", encoding="utf-8") as f:
                if len(f.readlines()) > 10:
                    f.seek(0)
                    self.logs = json.load(f)
                    self.loaded = True
                else:
                    self.logs = {"emp_id": -1, "day_logs": {}, "summary": {}}
        except (json.JSONDecodeError) as ex:
            logging.warning("Log file corrupted. Initializing empty logs.")
            raise ex
    
    def verify_change_in_user_on_this_system_uuid(self):
        url = config.keylogger_service_url.format(HOST=self.host)
        response = requests.get(url + config.verify_uuid_change.format(uuid=self.uuid))
        if response.status_code != 200:
            self.reset_logs()
        elif response.status_code == 200:
            data = response.json()
            emp_id = data.get("emp_id")
            if emp_id != self.logs["emp_id"]:
                self.reset_logs(emp_id)

    def reset_logs(self, id=-1):
        with open("productivity_logs.json", "r+", encoding="utf-8") as f:
            self.logs = {"emp_id": id, "day_logs": {}, "summary": {}}
            json.dump(self.logs, f)

    def send_metrics(self, payload):
        url = config.keylogger_service_url.format(HOST=self.host)
        response = requests.post(url, json=payload, headers=self.headers)
        print("Response persisting in server", response.content)

    def save_logs(self):
        while True:
            try:
                self.verify_change_in_user_on_this_system_uuid()
                with open("productivity_logs.json", "w") as f:
                    json.dump(self.logs, f, indent=4)
                    app_activity_filtered_payload = {}
                    app_activities = self.logs["day_logs"].get(self.today, {}).get("application_activity", None)
                    if app_activities:
                        for app_activity in app_activities:
                            app_activity_filtered_payload.update(
                                {
                                    app_activity: {
                                        "total_key_strokes": app_activities[app_activity]["total_key_strokes"]
                                    }
                                }
                            )
                        metrics_payload = {
                            "uuid": self.uuid,
                            "date": self.today,
                            "app_details": app_activity_filtered_payload,
                            "idle_time": self.logs["day_logs"][self.today]["idle_time"]
                        }
                        self.send_metrics(metrics_payload)
            except Exception as e:
                logging.error(f"Error saving logs: {e}")
                traceback.print_exc()
            time.sleep(self.log_interval)

    def count_valid_keystrokes(self, keys, max_idle=20):
        valid_keys_count = 0
        consecutive_count = 1  # Start by counting the first key
        last_key = None
    
        for i in range(1, len(keys)):
            current_key = keys[i]
    
            # Check if current key is the same as the previous one
            if current_key == last_key:
                consecutive_count += 1
            else:
                consecutive_count = 1  # Reset if keys differ
            
            # If the consecutive count is less than or equal to max_idle, count it
            if consecutive_count <= max_idle:
                valid_keys_count += 1
            
            last_key = current_key  # Update last_key to current one
        
        return valid_keys_count

    @property
    def today(self):
        return str(datetime.now().date())

    def aggregate_logs(self):
        today = self.today
        self.logs["day_logs"].setdefault(today, {
            "browser_activity": {},
            "application_activity": {},
            "idle_time": 0,
        })
    
        # Update browser activity with keys
        for url, activity in self.browser_logger.browser_time.get(today, {}).items():
            self.logs["day_logs"][today]["browser_activity"].setdefault(url, {
                "time_spent": activity.get("time_spent", 0),
                "visits": activity.get("visits", 0),
                "keys": [],
                "total_key_strokes": 0
            })
    
        # Update application activity with keys
        for app, time_spent in self.application_logger.app_time.items():
            self.logs["day_logs"][today]["application_activity"].setdefault(app, {
                "time_spent": time_spent,
                "keys": [],
                "total_key_strokes": 0
            })
    
        # Append keys to their corresponding activity
        for context, keys in self.keyboard_logger.key_data.items():
            temp_keys = keys
            self.keyboard_logger.key_data[context] = self.keyboard_logger.key_data[context][len(temp_keys):]
            if context in self.logs["day_logs"][today]["browser_activity"]:
                self.logs["day_logs"][today]["browser_activity"][context]["keys"].extend(temp_keys)

                self.logs["day_logs"][today]["browser_activity"][context]["total_key_strokes"] = self.count_valid_keystrokes(self.logs["day_logs"][today]["browser_activity"][context]["keys"])
            elif context in self.logs["day_logs"][today]["application_activity"]:
                self.logs["day_logs"][today]["application_activity"][context]["keys"].extend(temp_keys)
                self.logs["day_logs"][today]["application_activity"][context]["total_key_strokes"] = self.count_valid_keystrokes(self.logs["day_logs"][today]["application_activity"][context]["keys"])

        self.logs["day_logs"][today]["idle_time"] = self.idle_logger.total_idle_time

        # TODO: If needed enable the below.
        # Summary is optional but can include aggregated totals if needed
        #self.logs["summary"] = {
        #    "browser_activity": self.browser_logger.browser_history,
        #    "application_activity": self.application_logger.app_time,
        #    "idle_time": self.idle_logger.total_idle_time,
        #}

    def run(self):
        self.threads = [
            threading.Thread(target=self.keyboard_logger.track_keys, daemon=True),
            threading.Thread(target=self.save_logs, daemon=True),
        ]

        def track_activity():
            while True:
                self.browser_logger.log_browser_activity()
                self.application_logger.log_active_app()
                self.idle_logger.check_idle()
                self.aggregate_logs()
                time.sleep(self.log_interval)

        self.threads.append(threading.Thread(target=track_activity, daemon=True))

        for thread in self.threads:
            thread.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Shutting down tracker...")


if __name__ == "__main__":
    args = parser.parse_args()
    host = args.host
    interval = args.interval
    idletime = args.idletime
    if not host:
        sys.exit("Host IP is required")
    print(f"Option provided are\nHost : {host}\nInterval : {interval}\nIdle Time: {idletime}")
    tracker = ProductivityTracker(host=host, log_interval=interval or 300,idletime=idletime or 120)
    tracker.run()
