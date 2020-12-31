#! /usr/bin/env python3

APPINDICATOR_ID = 'kodi-playing'

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
try:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3
except:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3

import signal
import subprocess

# i18n: http://docs.python.org/3/library/gettext.html
import gettext
from gettext import gettext as _
gettext.textdomain(APPINDICATOR_ID)


class KodiPlayingIndicator():
    def __init__(self):
        # Create indicator object
        self.indicator = AppIndicator3.Indicator.new(APPINDICATOR_ID, 'kodi-playing', AppIndicator3.IndicatorCategory.OTHER)
        self.indicator.set_title('Kodi Playing')
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_menu(self.build_menu())

    def build_menu(self):
        """
        Build menu for the tray icon
        """
        menu = Gtk.Menu()
        
        item_now_playing = Gtk.MenuItem.new_with_label(_("Now Playing"))
        item_now_playing.connect('activate', self.show_current)
        menu.append(item_now_playing)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        item_log = Gtk.MenuItem.new_with_label(_("Show Log"))
        item_log.connect('activate', self.show_log)
        menu.append(item_log)
        
        item_settings = Gtk.MenuItem.new_with_label(_("Edit Settings"))
        item_settings.connect('activate', self.show_settings)
        menu.append(item_settings)
        
        menu.append(Gtk.SeparatorMenuItem())
        
        item_quit = Gtk.MenuItem.new_with_label(_('Quit'))
        item_quit.connect('activate', self.quit)
        menu.append(item_quit)
        
        menu.show_all()
                
        return menu
    
    def show_current(self, widget=None):
        subprocess.call(['kodi-playing', '-c'])
    
    def show_log(self, widget=None):
        subprocess.call(['kodi-playing', '-l'])
    
    def show_settings(self, widget=None):
        subprocess.call(['kodi-playing', '-s'])

    def quit(self, widget=None):
        subprocess.call(['kodi-playing', '-q'])
        Gtk.main_quit()

def main():
    KodiPlayingIndicator()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    Gtk.main()
    
if __name__ == '__main__':
    main()
