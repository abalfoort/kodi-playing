#! /usr/bin/env python3

# Purpose:      show notification what song Kodi is playing.
# Files:        $HOME/.kodi-playing
# References:
# i18n:         http://docs.python.org/3/library/gettext.html
# notify:       https://lazka.github.io/pgi-docs/#Notify-0.7
# appindicator: https://lazka.github.io/pgi-docs/#AyatanaAppIndicator3-0.1
# csv:          https://docs.python.org/3/library/csv.html
# jsonrpc:      https://kodi.wiki/view/JSON-RPC_API/v10
# Author:       Arjen Balfoort, 19-01-2021

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
try:
    from .utils import open_text_file, str_int
except:
    from utils import open_text_file, str_int


APPINDICATOR_ID = 'kodi-playing'


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
        self.csv = join(self.local_dir, 'kodi-playing.csv')
        self.tmp_thumb = '/tmp/kodi-playing.png'
        self.autostart_dt = join(self.home, '.config/autostart/kodi-playing-autostart.desktop')
        self.grey_icon = join(self.scriptdir, 'kodi-playing-grey.svg')
        self.config = ConfigParser()
        self.player_id = -1
        self.mediapath = ''
        self.position = -1
        
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
        if str_int(self.kodi_dict['kodi']['autostart'], 0) == 1:
            if not exists(self.autostart_dt):
                copyfile(join(self.scriptdir, 'kodi-playing-autostart.desktop'), self.autostart_dt)
        else:
            if exists(self.autostart_dt):
                os.remove(self.autostart_dt)
        
        # Create event to use when thread is done
        self.check_done_event = Event()
        # Create global indicator object
        self.indicator = AppIndicator3.Indicator.new(APPINDICATOR_ID, self.grey_icon, AppIndicator3.IndicatorCategory.OTHER)
        self.indicator.set_title('Kodi Playing')
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self.build_menu())
        # Init notifier
        Notify.init("%s:%s" % (self.address, self.port))
        # Start thread to check for connection changes
        Thread(target=self.run_check).start()

    def run_check(self):
        """ Poll Kodi for currently playing song. """
        # Initiate csv file (tab delimited)
        open(self.csv, 'w').close()
        # Initiate variables
        prev_title = ''
        prev_thumbnail_path = ''
        unable_notification = False
        
        while not self.check_done_event.is_set():
            # Check if kodi server is online
            if not self.is_connected(self.address, self.port):
                if not unable_notification:
                    self.player_id = -1
                    self.indicator.set_menu(self.build_menu())
                    self.indicator.set_icon_full(self.grey_icon, '')
                    self.show_notification(summary="%s %s:%s" % (_("Unable to connect to:"), self.address, self.port), 
                                           thumb='kodi-playing')
                    unable_notification = True
            else:
                # Save player id (-1: no active players)
                old_player_id = self.player_id
                self.player_id = self.get_player_id()
                if self.player_id < 0:
                    if old_player_id != self.player_id:
                        self.indicator.set_menu(self.build_menu())
                        self.indicator.set_icon_full(self.grey_icon, '')
                else:
                    if old_player_id != self.player_id:
                        # Connected: build menu and show normal icon
                        self.indicator.set_menu(self.build_menu())
                        self.indicator.set_icon_full('kodi-playing', '')
                    
                    # Reset variables
                    title = ''
                    artist = ''
                    album = ''
                    duration = ''
        
                    # Retrieve the title first
                    js = self.get_playing()
                    if js:
                        title = js['result']['item']['title']
                        artist = ' '.join(js['result']['item']['artist']).replace('"', '')
                        
                        # Check for season/episode
                        episode = ''
                        try:
                            if js['result']['item']['season'] > -1 and js['result']['item']['episode'] > -1:
                                episode = "S%sE%s" % (js['result']['item']['season'], js['result']['item']['episode'])
                        except:
                            pass
                        
                        # Save mediapath
                        self.mediapath = js['result']['item']['mediapath']
                        
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
                            try:
                                album = js['result']['item']['showtitle'].replace('"', '')
                            except:
                                album = js['result']['item']['album'].replace('"', '')
                            try:
                                duration = js['result']['item']['duration']
                            except:
                                duration = 0
                            
                            # Retrieve thumbnail path
                            thumbnail = js['result']['item']['thumbnail']
                            thumbnail_path = ''
                            if thumbnail:
                                thumbnail_path = self.get_thumbnail_path(thumb=thumbnail)
                                if thumbnail_path:
                                    # Save the thumbnail_path
                                    prev_thumbnail_path = thumbnail_path
                                else:
                                    thumbnail_path = prev_thumbnail_path
            
                            if title != artist:
                                # Logging
                                with open(self.csv, 'a') as f:
                                    f.write('{}\t{}\t{}\t{}\t{}\n'.format(title, artist, album, duration, thumbnail_path))
                                # Save playlist position
                                self.position = self.get_playlist_position()
                                # Send notification
                                self.show_song_info(index=1)
                            
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
        with open(self.csv, 'r') as f:
            for row in reversed(list(csv.reader(f, delimiter='\t'))):
                i += 1
                # We need to save the selected song
                # and the previous song to compare thumbnails
                if i == index or i == index + 1:
                    csv_data.append(row)
                    if i == index + 1:
                        break

        if csv_data:
            artist_title = "%s:" % _('Artist')
            album_title = _('Album')
            duration_title = _('Time')
            album_str = ''
            duration_str = ''
            duration = ''
            
            if not csv_data[0][1]:
                artist_title = ''
            if csv_data[0][2]:
                album_str = "<br>%s: %s" % (album_title, csv_data[0][2])
            if str_int(csv_data[0][3], 0) > 0:
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
            if self.notification_timeout > 0:
                self.show_notification(summary=csv_data[0][0], 
                                       body="%s %s %s %s" % (artist_title, csv_data[0][1], album_str, duration_str), 
                                       thumb=self.tmp_thumb)
            print(("%s, %s, %s, %s" % (csv_data[0][0], csv_data[0][1], csv_data[0][2], duration)))

    def json_request(self, kodi_request, address, port):
        """ Return json data from Kodi. """
        try:
            request = Request("http://%s:%s/jsonrpc" % (address, port), 
                              bytes(json.dumps(kodi_request), encoding='utf8'), 
                              {'Content-Type': 'application/json'})
            with closing(urlopen(request)) as response:
                return json.loads(response.read())
        except:
            return ''
        
    def get_player_id(self):
        """ Get player id and player type from Kodi. """
        kodi_request = {'jsonrpc': '2.0', 'method': 'Player.GetActivePlayers', 'id': 1}
        js = self.json_request(kodi_request=kodi_request,
                               address=self.address,
                               port=self.port)
        try:
            # Assume only one player
            return js['result'][0]['playerid']
        except:
            return -1

    def get_playing(self):
        """ Get what's playing data (json) from Kodi. """
        if self.player_id < 0: return ''
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.GetItem',
                        'params': { 'properties': ['title', 'album', 'artist', 'duration', 'thumbnail', 'showtitle', 'mediapath'], 'playerid': self.player_id },
                        'id': 1}            
        js = self.json_request(kodi_request=kodi_request,
                               address=self.address,
                               port=self.port)
        try:
            return js if js['result']['item']['title'] else ''
        except:
            return ''
    
    def get_thumbnail_path(self, thumb):
        try:
            # To get the full encrypted path we need to use Kodi's Files.PrepareDownload function
            kodi_request = {'jsonrpc': '2.0',
                            'method': 'Files.PrepareDownload',
                            'params': {'path': thumb}, 'method': 'Files.PrepareDownload', 'id': 'preparedl'}
            js = self.json_request(kodi_request=kodi_request,
                                   address=self.address,
                                   port=self.port)
            # Occasionally, this error is thrown: TypeError: string indices must be integers
            # In that case the previous thumbnail is used
            return "http://%s:%s/%s" % (self.kodi_dict['kodi']['address'],
                                        self.port,
                                        js['result']['details']['path'])
        except:
            return ''
        
    def get_playlist_position(self):
        """ Get current position in playlist. """
        if self.player_id < 0: return 0
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.GetProperties', 
                        'params': { 'playerid': self.player_id, 'properties': ['position'] }, 
                        'id': 1}
        js = self.json_request(kodi_request=kodi_request,
                               address=self.address,
                               port=self.port)
        try:
            return js['result']['position']
        except:
            return 0
    
    def play_pause_player(self):
        """ Toggle play/pause. """
        if 'plugin://' in self.mediapath:
            # You cannot pause streaming audio from a plugin
            if self.is_playing():
                self.stop_player()
            else:
                self.play_mediapath()
            # Set menu label
            self.set_play_pause_label()
        else:
            if self.player_id < 0:
                if self.position >= 0:
                    # Player was stopped (not paused) but we have a saved position
                    kodi_request = {'jsonrpc': '2.0',
                                    'method': 'Player.Open',
                                    'params': {'item': {'playlistid': 0, 'position': self.position}},
                                    'id': 1}
                    self.json_request(kodi_request=kodi_request,
                                      address=self.address,
                                      port=self.port)
                    # Reset position
                    self.position = -1
                else:
                    return
            else:
                # Play or pause media
                kodi_request = {'jsonrpc': '2.0',
                                'method': 'Player.PlayPause',
                                'params': { 'playerid': self.player_id },
                                'id': 1}
                self.json_request(kodi_request=kodi_request,
                                  address=self.address,
                                  port=self.port)
            # Set menu label
            self.set_play_pause_label()
            
    def play_mediapath(self):
        """ Start playing mediapath. """
        #kodi_request = {'jsonrpc': '2.0',
        #                'method': 'Player.Open',
        #                'params': {'item': {'file': self.mediapath}},
        #                'id': 1}
        
        # Workaround if above kodi_request is not working
        # https://forum.kodi.tv/showthread.php?tid=315249&pid=2694920#pid2694920
        kodi_request = [{'jsonrpc': '2.0',
                         'method': 'Playlist.Clear',
                         'params': {'playlistid': 0},
                         'id': 1},
                        {'jsonrpc': '2.0',
                         'method': 'Playlist.Add',
                         'params': {'playlistid': 0, 'item': {'file': self.mediapath}},
                         'id': 1},
                        {'jsonrpc': '2.0',
                         'method': 'Player.Open',
                         'params': {'item': {'playlistid': 0, 'position': 0}},
                         'id': 1}]
        self.json_request(kodi_request=kodi_request,
                          address=self.address,
                          port=self.port)
        
    def stop_player(self):
        """ Stop playing. """
        if self.player_id < 0: return
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.Stop',
                        'params': { 'playerid': self.player_id },
                        'id': 1}
        self.json_request(kodi_request=kodi_request,
                          address=self.address,
                          port=self.port)
        
    def system_shut_down(self):
        """ Shutdown system. """
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'System.Shutdown',
                        'id': 1}
        self.json_request(kodi_request=kodi_request,
                          address=self.address,
                          port=self.port)
        
    def system_reboot(self):
        """ Reboot system. """
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'System.Reboot',
                        'id': 1}
        self.json_request(kodi_request=kodi_request,
                          address=self.address,
                          port=self.port)
        
    def is_idle(self, seconds=60):
        """ Check if Kodi has been idle for x seconds. """
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'XBMC.GetInfoBooleans',
                        'params': { "booleans": ["System.IdleTime('{}')".format(seconds)] },
                        'id': 1}
        js = self.json_request(kodi_request=kodi_request,
                               address=self.address,
                               port=self.port)
        try:
            return js['result']["System.IdleTime('{}')".format(seconds)]
        except:
            return False
    
    def get_song_time_played(self):
        """ Get played seconds of currently playing song. """
        if self.player_id < 0: return 0
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.GetProperties',
                        'params': { 'playerid': self.player_id, 'properties': ['percentage', 'totaltime'] },
                        'id': 1}
        js = self.json_request(kodi_request=kodi_request,
                               address=self.address,
                               port=self.port)
        try:
            duration = (int(js['result']['totaltime']['minutes']) * 60) + int(js['result']['totaltime']['seconds'])
            return duration * (float(js['result']['percentage']) / 100)
        except:
            return 0
    
    def is_playing(self):
        """ Get played seconds of currently playing song. """
        if self.player_id < 0: return False
        kodi_request = {'jsonrpc': '2.0',
                        'method': 'Player.GetProperties',
                        'params': { 'playerid': self.player_id, 'properties': ['speed'] },
                        'id': 1}
        js = self.json_request(kodi_request=kodi_request,
                               address=self.address,
                               port=self.port)
        try:
            return True if int(js['result']['speed']) > 0 else False
        except:
            return False

    def is_connected(self, host, port):
        """ Check if Kodi server is online. """
        if not host:
            return False
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(1)
            try:
                if sock.connect_ex((host, port)) == 0:
                    return True
                else:
                    return False
            except:
                return False

    def search_kodi(self):
        """ Search local network for Kodi servers. """
        # Get list of network IPs
        ips = subprocess.check_output("arp -n | awk '{if(NR>1)print $1}'", shell=True).decode('utf-8').strip().split('\n')
        for ip in ips:
            if self.is_connected(host=ip,
                                 port=8080):
                return ip
                break
        return ''

    # ===============================================
    # System Tray Icon
    # ===============================================
    def build_menu(self):
        """ Build menu for the tray icon. """
        menu = Gtk.Menu()
        
        # Kodi menu
        item_kodi = Gtk.MenuItem.new_with_label('Kodi')
        sub_menu = Gtk.Menu()
        item_csv = Gtk.MenuItem.new_with_label(_("Show played songs"))
        item_csv.connect('activate', self.show_csv)
        sub_menu.append(item_csv)
        item_settings = Gtk.MenuItem.new_with_label(_("Edit settings"))
        item_settings.connect('activate', self.show_settings)
        sub_menu.append(item_settings)
        item_shut_down = Gtk.MenuItem.new_with_label(_('Shut down'))
        item_shut_down.connect('activate', self.shut_down)
        sub_menu.append(item_shut_down)
        item_reboot = Gtk.MenuItem.new_with_label(_('Reboot'))
        item_reboot.connect('activate', self.reboot)
        sub_menu.append(item_reboot)
        item_kodi.set_submenu(sub_menu)
        menu.append(item_kodi)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        item_now_playing = Gtk.MenuItem.new_with_label(_("Now playing"))
        item_now_playing.connect('activate', self.show_current)
        menu.append(item_now_playing)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        self.item_play_pause = Gtk.MenuItem.new()
        self.set_play_pause_label()
        self.item_play_pause.connect('activate', self.play_pause)
        menu.append(self.item_play_pause)
        
        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem.new_with_label(_('Quit'))
        item_quit.connect('activate', self.quit)
        menu.append(item_quit)
        
        menu.show_all()

        if self.is_connected(self.address, self.port):
            if self.player_id >= 0:
                item_now_playing.set_sensitive(True)
            else:
                item_now_playing.set_sensitive(False)
            self.item_play_pause.set_sensitive(True)
            item_shut_down.set_sensitive(True)
            item_reboot.set_sensitive(True)
            item_csv.set_sensitive(True)
        else:
            item_now_playing.set_sensitive(False)
            self.item_play_pause.set_sensitive(False)
            item_csv.set_sensitive(False)
            item_shut_down.set_sensitive(False)
            item_reboot.set_sensitive(False)

        return menu
    
    def set_play_pause_label(self):
        """ Set label for play/pause button """
        if self.is_playing():
            self.item_play_pause.set_label(" ▯▯")
        else:
            self.item_play_pause.set_label(" ▷")
    
    def show_current(self, widget=None):
        """ Show last played song. """
        self.show_song_info(1)
        if exists(self.tmp_thumb):
            os.remove(self.tmp_thumb)
        
    def show_index(self, widget, index):
        """ Menu function to call show_song_info with index. """
        self.show_song_info(index=index)
        
    def play_pause(self, widget=None):
        """ Menu function to call play_pause_player. """
        self.play_pause_player()
    
    def show_csv(self, widget=None):
        """ Open kodi-playing.csv in default editor. """
        subprocess.call(['xdg-open', self.csv])
    
    def show_settings(self, widget=None):
        """ Open settings.ini in default editor. """
        if exists(self.conf):
            open_text_file(self.conf)
            self.read_config()
            
    def shut_down(self, widget=None):
        """ Menu function to call system_shut_down. """
        self.system_shut_down()
        
    def reboot(self, widget=None):
        """ Menu function to call system_reboot. """
        self.system_reboot()
        
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
        self.port = str_int(self.kodi_dict['kodi']['port'], 8080)
        self.wait = str_int(self.kodi_dict['kodi']['wait'], 10)
        self.notification_timeout = str_int(self.kodi_dict['kodi']['show_notification'], 10)
    
    def show_notification(self, summary, body=None, thumb=None):
        """ Show the notification. """
        notification = Notify.Notification.new(summary, body, thumb)
        notification.set_timeout(self.notification_timeout * 1000)
        notification.set_urgency(Notify.Urgency.LOW)
        notification.show()
