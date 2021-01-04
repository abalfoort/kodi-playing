#! /usr/bin/env python3

# Purpose:  show notification what song Kodi is playing.
# Files:    $HOME/.kodi-playing
# Author:   Arjen Balfoort, 02-01-2021

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
try:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3
except:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
gi.require_version('Notify', '0.7')
from gi.repository import Notify
from gi.repository import Gio

import os
import sys
import csv
import subprocess
import signal
import datetime
import json
import socket
from shutil import copyfile
from time import gmtime, strftime, sleep
from pathlib import Path
from configparser import ConfigParser
from urllib.request import Request, urlopen, urlretrieve
from contextlib import closing
from os.path import abspath, dirname, join, exists
from threading import Event, Thread


APPINDICATOR_ID = 'kodi-playing'

# i18n: http://docs.python.org/3/library/gettext.html
import gettext
from gettext import gettext as _
gettext.textdomain(APPINDICATOR_ID)


class KodiPlaying():
    def __init__(self):
        # Initiate variables
        self.scriptdir = abspath(dirname(__file__))
        self.home = str(Path.home())
        self.local_dir = join(self.home, '.kodi-playing')
        self.conf = join(self.local_dir, 'settings.ini')
        self.log = join(self.local_dir, 'kodi-playing.csv')
        self.tmp_thumb = '/tmp/kodi-playing.png'
        self.autostart_dt = join(self.home, '.config/autostart/kodi-playing-autostart.desktop')
        self.is_connected = False
        self.prev_is_connected = False
        self.is_playing = False
        self.prev_is_playing = False
        self.grey_icon = join(self.scriptdir, 'kodi-playing-grey.svg')
        self.config = ConfigParser()
        
        # Create local directory
        os.makedirs(self.local_dir, exist_ok=True)
        # Create conf file if it does not already exist
        if not exists(self.conf):
            # Search for kodi on the network
            kodi = self.search_kodi()
            cont = ''
            # Get default settings
            with open(join(self.scriptdir, 'settings.ini'), 'r') as f:
                cont = f.read()
            if kodi:
                cont = cont.replace('localhost', kodi)
            # Save settings.ini
            with open(self.conf, 'w') as f:
                f.write(cont)
            # Let the user configure the settings and block the process until done
            self.show_settings()
            
        # Read the ini into a dictionary
        self.read_config()

        # Check if configured for autostart
        if self.str_int(self.kodi_dict['kodi']['autostart'], 0) == 1:
            if not exists(self.autostart_dt):
                copyfile(join(self.scriptdir, 'kodi-playing-autostart.desktop'), self.autostart_dt)
        else:
            if exists(self.autostart_dt):
                os.remove(self.autostart_dt)
        
        # Create event to use when thread is done
        self.check_done_event = Event()
        # Create global indicator object
        # https://lazka.github.io/pgi-docs/#AyatanaAppIndicator3-0.1
        self.indicator = AppIndicator3.Indicator.new(APPINDICATOR_ID, self.grey_icon, AppIndicator3.IndicatorCategory.OTHER)
        self.indicator.set_title('Kodi Playing')
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self.build_menu())
        self.indicator.set_secondary_activate_target(self.item_now_playing)
        # Init notifier
        # https://lazka.github.io/pgi-docs/#Notify-0.7
        Notify.init("%s:%s" % (self.address, self.port))
        # Start thread to check for connection changes
        Thread(target=self.run_check).start()

    def run_check(self):
        """ Poll Kodi for currently playing song. """
        # Initiate log file (tab seperated csv)
        open(self.log, 'w').close()
        # Initiate variables
        prev_title = ''
        prev_thumbnail_path = ''
        
        while not self.check_done_event.is_set():
            # Get json data from Kodi
            js = ''
            while not js:
                if self.check_done_event.is_set():
                    break
                # Kodi not running - keep checking
                js = self.get_song()
                if not js:
                    self.is_connected = False
                    if self.prev_is_connected:
                        # Lost connection: rebuild menu
                        self.prev_is_connected = False
                        self.indicator.set_menu(self.build_menu())
                        self.indicator.set_icon_full(self.grey_icon, '')
                        self.check_done_event.wait(self.wait)
            
            # Go not any further if json is empty
            if not js:
                break
            
            # Connected: build menu and show normal icon
            self.is_connected = True
            if not self.prev_is_connected:
                self.prev_is_connected = True
                self.indicator.set_menu(self.build_menu())
                self.indicator.set_icon_full('kodi-playing', '')
            
            # Check if there is something playing
            self.set_is_playing()
            if self.is_playing != self.prev_is_playing:
                self.prev_is_playing = self.is_playing
                self.indicator.set_menu(self.build_menu())

            # Reset variables
            title = ''
            artist = ''
            album = ''
            duration = ''

            # Retrieve the title first
            title = js['result']['item']['title']
            artist = ' '.join(js['result']['item']['artist']).replace('"', '')
            
            # Radio plugin title: split on ' - '
            # https://kodi.wiki/view/Add-on:Radio
            if not artist:
                arr = title.split(' - ')
                if len(arr) == 2:
                    artist = arr[0]
                    title = arr[1]
            
            # Check if we need to skip this title
            skip = False
            for pattern in self.kodi_dict['kodi']['skip_titles'].split(','):
                if pattern in title:
                    skip = True
                    break

            if not skip and title and title !=  prev_title:
                # Get album and duration
                album = js['result']['item']['album'].replace('"', '')
                duration = js['result']['item']['duration']
                
                # Retrieve thumbnail path
                thumbnail = js['result']['item']['thumbnail']
                thumbnail_path = ''
                if thumbnail:
                    thumbnail_path = self.get_thumbnail_path(thumbnail)
                    if thumbnail_path:
                        # Save the thumbnail_path
                        prev_thumbnail_path = thumbnail_path
                    else:
                        thumbnail_path = prev_thumbnail_path

                if title !=  artist:
                    # Logging
                    with open(self.log, 'a') as f:
                        f.write('{}\t{}\t{}\t{}\t{}\n'.format(title, artist, album, duration, thumbnail_path))
                    # Send notification
                    self.show_song_info(1)
                
                # Save the title for the next loop
                prev_title = title

            # Wait until we continue with the loop
            self.check_done_event.wait(self.wait)
            
    # ===============================================
    # Kodi functions
    # ===============================================

    def show_song_info(self, index):
        """ Show song information in notification. """
        # Get last two songs from csv data
        csv_data = []
        i = 0
        with open(self.log, 'r') as f:
            # https://docs.python.org/3/library/csv.html
            for row in reversed(list(csv.reader(f, delimiter='\t'))):
                i += 1
                # We need to save the selected song
                # and the previous song to compare thumbnails
                if i == index or i == index + 1:
                    csv_data.append(row)
                    if i == index + 1:
                        break

        if csv_data:
            artist_title = _('Artist')
            album_title = _('Album')
            duration_title = _('Time')
            album_str = ''
            duration_str = ''
            
            if csv_data[0][2]:
                album_str = "<br>%s: %s" % (album_title, csv_data[0][2])
            if self.str_int(csv_data[0][3], 0) > 0:
                # Convert to "00:00" notation
                duration = strftime("%M:%S", gmtime(int(csv_data[0][3])))
                played = duration
                if index == 1:
                    # Get time played
                    played = self.get_song_time_played()
                    # Convert to "00:00" notation
                    played = strftime("%M:%S", gmtime(played))
                duration_str = "<br>%s: %s (%s)" % (duration_title, played, duration)

            if csv_data[0][4]:
                # Check with previous song before downloading thumbnail
                if not exists(self.tmp_thumb) or len(csv_data) == 1:
                    urlretrieve(csv_data[0][4], self.tmp_thumb)
                elif len(csv_data) > 1:
                    if csv_data[0][4] != csv_data[1][4] or index > 1:
                        urlretrieve(csv_data[0][4], self.tmp_thumb)

            # Show notification
            Notify.Notification.new(csv_data[0][0], 
                                    "%s: %s %s %s" % (artist_title, csv_data[0][1], album_str, duration_str), 
                                    self.tmp_thumb).show()
            print(("%s, %s: %s, %s: %s, %s: %s" % (csv_data[0][0], artist_title, csv_data[0][1], album_title, csv_data[0][2], duration_title, csv_data[0][3])))

    def json_request(self, kodi_request, address, port):
        """ 
        Return json data from Kodi. 
        https://kodi.wiki/view/JSON-RPC_API/v10
        """
        try:
            request = Request("http://%s:%s/jsonrpc" % (address, port), 
                              bytes(json.dumps(kodi_request), encoding='utf8'), 
                              {'Content-Type': 'application/json'})
            with closing(urlopen(request)) as response:
                return json.loads(response.read())
        except:
            return ''

    def get_song(self):
        """ Get song data (json) from Kodi. """
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.GetItem',
                        'params': { 'properties': ['title', 'album', 'artist', 'duration', 'thumbnail'], 'playerid': 0 },
                        'id': 'AudioGetItem'}
        js = self.json_request(kodi_request, self.address, self.port)
        try:
            if js['result']['item']['title']:
                return js
            else:
                return ''
        except:
            return ''
            
    
    def get_thumbnail_path(self, thumbnail):
        try:
            # To get the full encrypted path we need to use Kodi's Files.PrepareDownload function
            kodi_request = {'jsonrpc': '2.0',
                            'method': 'Files.PrepareDownload',
                            'params': {'path': thumbnail}, 'method': 'Files.PrepareDownload', 'id': 'preparedl'}
            js_thumb = self.json_request(kodi_request, self.address, self.port)
            # Occasionally, this error is thrown: TypeError: string indices must be integers
            # In that case the previous thumbnail is used
            return "http://%s:%s/%s" % (self.kodi_dict['kodi']['address'],
                                        self.port,
                                        js_thumb['result']['details']['path'])
        except:
            return ''
    
    def play_pause_song(self):
        """ Toggle play/pause. """
        if not self.is_connected:
            return
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.PlayPause',
                        'params': { 'playerid': 0 },
                        'id': 1}
        self.json_request(kodi_request, self.address, self.port)
        
    def is_idle(self, seconds=60):
        """ Check if Kodi has been idle for x seconds. """
        if not self.is_connected:
            return True
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'XBMC.GetInfoBooleans',
                        'params': { "booleans": ["System.IdleTime('{}')".format(seconds)] },
                        'id': 1}
        js = self.json_request(kodi_request, self.address, self.port)
        try:
            return js['result']["System.IdleTime('{}')".format(seconds)]
        except:
            return False
    
    def get_song_time_played(self):
        """ Get played seconds of currently playing song. """
        if not self.is_connected:
            return 0
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.GetProperties',
                        'params': { 'playerid': 0, 'properties': ['percentage', 'totaltime'] },
                        'id': 1}
        js = self.json_request(kodi_request, self.address, self.port)
        try:
            duration = (int(js['result']['totaltime']['minutes']) * 60) + int(js['result']['totaltime']['seconds'])
            return duration * (float(js['result']['percentage']) / 100)
        except:
            return 0
    
    def set_is_playing(self):
        """ Get played seconds of currently playing song. """
        if not self.is_connected:
            self.is_playing = False
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.GetProperties',
                        'params': { 'playerid': 0, 'properties': ['speed'] },
                        'id': 1}
        js = self.json_request(kodi_request, self.address, self.port)
        try:
            self.is_playing = True if int(js['result']['speed']) == 1 else False
        except:
            self.is_playing = False
            
    def search_kodi(self):
        port = 8080
        # Get list of network IPs
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.GetActivePlayers',
                        'id': 1}
        ips = subprocess.check_output("arp -n | awk '{if(NR>1)print $1}'", shell=True).decode('utf-8').strip().split('\n')
        for ip in ips:
            if ip:
                # First check if port is open
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                #sock.setblocking(False)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    # Now check if json is available
                    js = self.json_request(kodi_request, ip, port)
                    if js:
                        return ip
                        break
        return ''
    
    # ===============================================
    # System Tray Icon
    # ===============================================
    def build_menu(self):
        """ Build menu for the tray icon. """
        menu = Gtk.Menu()
        
        self.item_now_playing = Gtk.MenuItem.new_with_label(_("Current song"))
        self.item_now_playing.connect('activate', self.show_current)
        menu.append(self.item_now_playing)
        
        # Song by index
        item_index = Gtk.MenuItem.new_with_label(_("Song by index"))
        sub_menu = Gtk.Menu()
        sub_item_index_2 = Gtk.MenuItem.new_with_label("2 - %s" % _("previous"))
        sub_item_index_2.connect('activate', self.show_index, 2)
        sub_menu.append(sub_item_index_2)
        sub_item_index_3 = Gtk.MenuItem.new_with_label('3')
        sub_item_index_3.connect('activate', self.show_index, 3)
        sub_menu.append(sub_item_index_3)
        sub_item_index_4 = Gtk.MenuItem.new_with_label('4')
        sub_item_index_4.connect('activate', self.show_index, 4)
        sub_menu.append(sub_item_index_4)
        sub_item_index_5 = Gtk.MenuItem.new_with_label('5')
        sub_item_index_5.connect('activate', self.show_index, 5)
        sub_menu.append(sub_item_index_5)
        item_index.set_submenu(sub_menu)
        menu.append(item_index)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        if self.is_playing:
            item_pp = Gtk.MenuItem.new_with_label(" ▯▯")
        else:
            item_pp = Gtk.MenuItem.new_with_label(" ▷")
        item_pp.connect('activate', self.play_pause)
        menu.append(item_pp)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        item_log = Gtk.MenuItem.new_with_label(_("Show log"))
        item_log.connect('activate', self.show_log)
        menu.append(item_log)
        
        item_settings = Gtk.MenuItem.new_with_label(_("Edit settings"))
        item_settings.connect('activate', self.show_settings)
        menu.append(item_settings)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        item_quit = Gtk.MenuItem.new_with_label(_('Quit'))
        item_quit.connect('activate', self.quit)
        menu.append(item_quit)
        
        menu.show_all()
        
        if self.is_connected:
            self.item_now_playing.set_sensitive(True)
            item_index.set_sensitive(True)
            item_pp.set_sensitive(True)
        else:
            self.item_now_playing.set_sensitive(False)
            item_index.set_sensitive(False)
            item_pp.set_sensitive(False)

        return menu
    
    def show_current(self, widget=None):
        """ Show last played song. """
        self.show_song_info(1)
        if exists(self.tmp_thumb):
            os.remove(self.tmp_thumb)
        
    def show_index(self, widget, index):
        """ Menu function to call show_song_info with index. """
        self.show_song_info(index)
        
    def play_pause(self, widget=None):
        """ Menu function to call play_pause_song. """
        self.play_pause_song()
        self.indicator.set_menu(self.build_menu())
    
    def show_log(self, widget=None):
        """ Open kodi-playing.csv in default editor. """
        subprocess.call(['xdg-open', self.log])
    
    def show_settings(self, widget=None):
        """ Open settings.ini in default editor. """
        if exists(self.conf):
            subprocess.call(['xdg-open', self.conf])
            # Get the pid of opened file
            # Posted on stackoverflow: https://stackoverflow.com/questions/65544182/python3-linux-open-text-file-in-default-editor-and-wait-until-done
            pid = subprocess.check_output("ps -o pid,cmd -e | grep %s | head -n 1 | awk '{print $1}'" % self.conf, shell=True).decode('utf-8')
            while self.check_pid(pid):
                sleep(1)
            self.read_config()
        
    # ===============================================
    # General functions
    # ===============================================

    def quit(self, widget=None):
        """ Quit the application. """
        self.check_done_event.set()
        Notify.uninit()
        Gtk.main_quit()
        
    def read_config(self):
        """ Read settings.ini, save in dictionary and check some variables. """
        self.config.read(self.conf)
        self.kodi_dict = {s:dict(self.config.items(s)) for s in self.config.sections()}
        # Save port and default to 8080
        self.address = self.kodi_dict['kodi']['address']
        self.port = self.str_int(self.kodi_dict['kodi']['port'], 8080)
        self.wait = self.str_int(self.kodi_dict['kodi']['wait'], 10)
        
    def str_int(self, nr_str, default_int):
        """ Convert string to integer or return default value. """
        try:
            return int(nr_str)
        except ValueError:
            return default_int
        
    def check_pid(self, pid):        
        """ Check For the existence of a unix pid. """
        try:
            os.kill(int(pid), 0)
        except OSError:
            return False
        else:
            return True

def main():
    KodiPlaying()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()
    
if __name__ == '__main__':
    main()
