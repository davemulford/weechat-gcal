#!/usr/bin/env python

from __future__ import print_function
import weechat
import sys
import pickle
import json
import math
import os.path
from datetime import datetime
from datetime import date
from datetime import timedelta
from dateutil.parser import parse as datetime_parse
from os.path import expanduser

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# TODO: Add settings
# minutes_remaining = [5, 10, 15]
# notify_enabled = yes/no
# time_format = '%H:%M' ???

SCRIPT_NAME = 'weechat-gcal'
SCRIPT_AUTHOR = 'Dave Mulford'
SCRIPT_VERSION = '0.1'
SCRIPT_LICENSE = 'GPL2'
SCRIPT_DESC = 'A Google Calendar integration script that provides notifications of upcoming events.'
SCRIPT_SHUTDOWN_FN = ''
SCRIPT_CHARSET = ''

TIMEOUT_MS = 3000

CALLED_FROM_CMD = '100'
CALLED_FROM_TIMER = '200'

NOTIFICATION_THRESHOLDS = [5,15]

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Where the weechat-gcal-token.pickle file is located
CACHE_DIR = os.path.join(expanduser('~'), '.cache', 'weechat-gcal')

# =============================
# GOOGLE CALENDAR FUNCTIONS
# =============================

def _load_credentials(creds_file=None):
    """Loads the credentials from a credentials.json file or by prompting for authentication.
    Returns a credentials object to be used by the Google Sheets API.
    """

    creds = None

    # Validate the credentials file
    if not creds_file:
        creds_file = 'credentials.json'
    if not os.path.exists(creds_file):
        creds_file = os.path.join(expanduser('~'), 'credentials.json')
    if not os.path.exists(creds_file):
        raise SystemExit('Could not find a credentials.json file. ' \
                'Either pass one as argument or make sure credentials.json exists in ' \
                'the current directory or ' + expanduser('~'))

    # Creates CACHE_DIR if it does not exist
    # mode 0x777 (the default) is used because the system's umask value is masked out first
    if not os.path.exists(CACHE_DIR):
        os.mkdir(CACHE_DIR)

    pickle_filename = os.path.join(CACHE_DIR, 'weechat-gcal-token.pickle')

    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists(pickle_filename):
        with open(pickle_filename, 'rb') as token:
            creds = pickle.load(token)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        with open(pickle_filename, 'wb') as token:
            pickle.dump(creds, token)

    return creds

def gc_get_events(num_events=50):
    creds = _load_credentials()
    service = build('calendar', 'v3', credentials=creds)

    # Call the Calendar API
    now = datetime.utcnow().isoformat() + 'Z' # 'Z' indicates UTC time
    tomorrow = datetime.combine( \
                    date.today() + timedelta(days=2), \
                    datetime.min.time()) \
                .isoformat() + 'Z'

    #print('Getting the upcoming {} events between {} and {}'.format(num_events, now, tomorrow))
    events_result = service.events().list(calendarId='primary', timeMin=now, timeMax=tomorrow,
                                        maxResults=num_events, singleEvents=True,
                                        orderBy='startTime').execute()
    events = events_result.get('items', [])
    return events

# =============================
# WEECHAT HELPER FUNCTIONS
# =============================

def buffer_get():
    """Finds or creates a buffer to use for script output.
        Returns a buffer pointer.
    """
    buffer = weechat.buffer_search('python', SCRIPT_NAME)

    if not buffer:
        buffer = weechat.buffer_new(SCRIPT_NAME, 'buffer_input', '', '', '')
        weechat.buffer_set(buffer, 'time_for_each_line', '0')
        weechat.buffer_set(buffer, 'nicklist', '0')
        weechat.buffer_set(buffer, 'title', 'Google Calendar')
        weechat.buffer_set(buffer, 'localvar_set_no_log', '1')

    return buffer

def buffer_input(data, buffer, input_data):
    """A function called when text, that is not a command, is entered
        in the weechat-gcal buffer. This function exists to prevent
        errors from being shown, there is no functionality.
    """
    return weechat.WEECHAT_RC_OK

def update_gcal_buffer(buffer, events):
    weechat.buffer_clear(buffer)

    if events == []:
        weechat.prnt(buffer, 'No events for now. YAY!!!')

    dates = {}
    for event in events:
        dt = datetime_parse(event['date'])
        datestr = dt.strftime('%a %Y-%m-%d')
        timestr = dt.strftime('%H:%M')

        if datestr not in dates:
            dates[datestr] = []

        dates[datestr].append({
            'time': timestr,
            'summary': event['summary']
        })

    for datestr in dates.keys():
        weechat.prnt(buffer, datestr)

        dt_events = dates[datestr]
        for event in dt_events:
            weechat.prnt(buffer, '{} {}'.format(event['time'], event['summary']))

# =============================
# MAIN SCRIPT FUNCTIONS
# =============================

def get_calendar(*args):
    result = []

    try:
        events = gc_get_events()

        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            result.append({
                'date': start,
                'summary': event['summary']
            })
    except Exception as err:
        result = err

    return json.dumps(result)

def get_calendar_callback(data, command, return_code, out, err):
    result = json.loads(out)

    buffer = buffer_get()
    update_gcal_buffer(buffer, result)

    # Notify if any events are happening in 10 minutes!
    if data == CALLED_FROM_TIMER:
        for event in result:
            #weechat.prnt(buffer, 'Handling event!')
            dt = datetime_parse(event['date'])
            now = datetime.now(tz=dt.tzinfo)
            timediff = dt - now
            minutes_remaining = math.ceil(timediff.total_seconds() / 60)

            #weechat.prnt(buffer, '{} - {} = {} ({} mins)'.format(dt, now, timediff, minutes_remaining))

            # TODO Make minutes_remaining threshold configurable
            if minutes_remaining in NOTIFICATION_THRESHOLDS:
                msg = '[{}m] {}'.format(minutes_remaining, event['summary'])
                weechat.prnt_date_tags(buffer, 0, 'notify_highlight', msg)

    return weechat.WEECHAT_RC_OK

def gcal_command(data, buffer, args):
    buffer = buffer_get()

    # TODO Implement init
    if args == 'init':
        pass
    else:
        weechat.hook_process(
            'func:get_calendar',
            TIMEOUT_MS,
            'get_calendar_callback',
            CALLED_FROM_CMD
        )

    return weechat.WEECHAT_RC_OK

def script_main(data, remaining_calls):
    # Weechat is single-threaded so a new process is created so other things aren't held up
    # if retrieving Google Calendar events doesn't return in a timely manner.
    # https://weechat.org/files/doc/stable/weechat_scripting.en.html#weechat_architecture
    weechat.hook_process(
        'func:get_calendar',
        TIMEOUT_MS,
        'get_calendar_callback',
        CALLED_FROM_TIMER
    )

    return weechat.WEECHAT_RC_OK

# Register the script on /script load
# This needs to happen first!
weechat.register(SCRIPT_NAME, SCRIPT_AUTHOR, SCRIPT_VERSION, \
                    SCRIPT_LICENSE, SCRIPT_DESC, SCRIPT_SHUTDOWN_FN, SCRIPT_CHARSET)

# Setup a command to initialize the Google Calendar authentication and show events in a buffer.
weechat.hook_command(
    'gcal',
    'Displays events for today and tomorrow in a new buffer.',
    '[init]',
    ' || init - Initializes the items needed for this plugin to work.',
    '',
    'gcal_command',
    ''
)

# Check once per minute whether we should notify of imminent events
weechat.hook_timer(60000, 60, 0, 'script_main', '')
