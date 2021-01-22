---
layout: page
title: KODI-PLAYING
section: 1
footer: "Kodi Playing"
header: "Kodi Playing"
date: December 2020
---

# NAME

kodi-playing - Show a notification when your Kodi server is playing a new song.

# DESCRIPTION

The indicator sits in the system tray and shows what Kodi is playing.

* Changes in settings will be aplied the next time you start kodi-playing.
* All played songs are saved to a tab-delimited csv file. This file is recreated each time kodi-playing is started.
* Shutdown or reboot the system.
* Play/pause media.

# SETTINGS

These settings can be configured in the settings.ini file (see below):

address = localhost
:   Kodi name/IP address

port = 8080
:   Kodi port (default: 8080)

wait = 10
:   Wait nr seconds for next Kodi check (default: 10)

show_notification = 10
:   Show notification nr seconds (default: 10, disable: 0)

skip_titles = NPO,KINK
:   Skip title with one of these patterns (comma separated)

autostart = 0
:   Autostart on login (0: no, 1: yes, default: 0)


# FILES

~/.kodi-playing/settings.ini
:   Configuration file.

~/.kodi-playing/kodi-playing.csv
:   Kodi data of kodi-playing session.

~/.kodi-playing/error.log
:   In case of an unexpected error this file contains the traceback.

# Author

Written by Arjen Balfoort

# BUGS

https://gitlab.com/abalfoort/kodi-playing/-/issues


