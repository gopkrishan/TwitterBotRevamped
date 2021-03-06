#!/usr/bin/env python3

import sys, time, twitter, spotipy
import datetime, traceback
import mysql.connector
import spotipy.util as util

sys.path.append('../')
from sp_utils import *
from env import env
from twitter_functions import twitter_functions as twitfunc

# Functions

# Gets the current time
def get_curr_time():
    t = datetime.datetime.now()
    return t.strftime("%Y-%m-%d-%X")

# Prints information about the current state to terminal if required
def check_printed(printed, state, format = None):

    state_strings = [
        "[{}] No user currently logged in, sleeping until somebody logs in!",
        "[{}] Have not listened to enough of the song!",
        "--------------------------------------------------------------------------\n\033[32mSucessful Tweet!\u001b[0m\n{}--------------------------------------------------------------------------",
        "[{}] The current song is still the previous song!",
        "[{}] Not currently playing anything, waiting for playback to resume!"
    ]

    if not printed:
        if state != 2:
            print(state_strings[state].format(get_curr_time()))

        else:
            print(state_strings[state].format(format))

# Tweets the current song if able too. Also searches for varified artists' twitter handles on twitter
def tweet_song(sp, e, state):

    try:
        # Twitter Authentication
        twit = twitter.Api(consumer_key=e.twit_consumer_key,
        consumer_secret=e.twit_consumer_secret,
        access_token_key=e.twit_access_token_key,
        access_token_secret=e.twit_access_token_secret)

        tf = twitfunc()

        tr_artist = tf.lookup_user(twit = twit, query = sp.ct_artists_list)
        status = twit.PostUpdate("Current Track: " + sp.ct_name + "\nArtists: " + sp.ct_artists + "\nListen now at: " + sp.ct_url)
        tweet_info = str("\033[34mTweet: \u001b[0m\n" + status.text + "\n\033[33mTweet ID: \u001b[0m" + status.id_str + "\n\033[31mTimestamp: \u001b[0m" + status.created_at + "\n")
        check_printed(False, state, tweet_info)
        with open(sys.argv[1], "a") as log:
            log.write("---------------------------------------------------------------------------\n")
            log.write("\033[32mSucessful Tweet!\u001b[0m\n")
            log.write(tweet_info)
        sp.ct_artists_list = []
        sp.tweeted = True

    except twitter.error.TwitterError as err:
        print("This song has already been tweeted!\n" + repr(err))

    except twitfunc.InvalidTwitterAuthError as err:
        print(err)

def update_db(sp, e):

    try:
        mydb = mysql.connector.connect(
            host=e.mysql_host,
            user=e.mysql_user,
            passwd=e.mysql_pw,
            database=e.mysql_db
        )

        mycursor = mydb.cursor()

        sql = """INSERT INTO SpTrackInfo (tr_uri, tr_name, ar_uri, ar_name, num_artists, AllTime_Num_Playbacks, Weekly_Num_Playbacks) \
                 VALUES (%s, %s, %s, %s, %s, %s, %s) \
                 ON DUPLICATE KEY \
                 UPDATE AllTime_Num_Playbacks = AllTime_Num_Playbacks + 1, Weekly_Num_Playbacks = Weekly_Num_Playbacks + 1"""

        val = (sp.ct_uri, sp.ct_name, list(sp.ct_artist_uri.keys())[0], sp.ct_artists, sp.ct_num_artists, 1, 1)
        mycursor.execute(sql, val)

        mydb.commit()

        print(mycursor.rowcount, "record inserted into SpTrackInfo in DB TBR.")

    except mysql.connector.Error as error:
        mydb.rollback() # rollback if any exception occured
        print("Failed inserting record into SpTrackInfo {}".format(error))

    finally:

        # closing database connection.
        if(mydb.is_connected()):
            mycursor.close()
            mydb.close()

# Infinite loop that Initalizing everything, including state machine
def mainLoop():

    # Setting up Enviornment IE: Keys, and needed objs
    e = env()
    sp = spot(e)
    prev_tr_uri = str()
    state = 0
    printed = False

    # This is the main loop that the program will run.
    # States and their associated value:
    #
    # no_user = 0
    # prog_lt_tqp = 1
    # tweet_song = 2
    # prog_gt_tqp = 3
    # wait_for_resume = 4
    while True:

        # Spotify Authentication
        sp.update_obj(e)

        # No User
        if state == 0:
            if sp.sp_obj is not None:
                if not sp.ct_is_playing:
                    state = 4
                    printed = False

                else:
                    state = 1
                    printed = False
            else:
                check_printed(printed, state)
                state = 0
                printed = True

        # Progress < 3/4 track Lenght
        elif state == 1 and sp.sp_obj is not None:
            if not sp.ct_is_playing:
                state = 4
                printed = False

            elif (sp.ct_is_playing and
                 (3*sp.ct_length)/4 < sp.ct_progress and
                 not sp.tweeted and
                 sp.ct_uri == prev_tr_uri):
                state = 2
                printed = False

            else:
                # If the song is different from the previous song, then set tweeted to false
                if sp.ct_uri != prev_tr_uri:
                    sp.tweeted = False

                prev_tr_uri = sp.ct_uri
                check_printed(printed, state)
                state = 1
                printed = True

        # Tweet Song
        elif state == 2:

            # Apparently it is possible to get into this state without a valid obj
            if sp.sp_obj is not None and sp.ct_name == "":
                print("[{}]\033[31mWaring!\u001b[0m: Spotify object exists but no data filled! Forcing state 0!".format(get_curr_time()))
                state = 0
                continue

            sp_obj_ready = sp
            tweet_song(sp_obj_ready, e, state)
            update_db(sp_obj_ready, e)
            prev_tr_uri = sp.ct_uri
            state = 3
            printed = False
            sp_obj_ready = None

        # Progress > 3/4 track length && Tweeted
        elif state == 3 and sp.sp_obj is not None:
            if not sp.ct_is_playing:
                state = 4
                printed = False

            elif sp.ct_uri != prev_tr_uri:
                state = 1
                printed = False
                sp.tweeted = False

            else:
                check_printed(printed, state)
                state =  3
                printed = True

        # Waiting for Playback to be Resumed
        elif state == 4 and sp.sp_obj is not None:
            if sp.ct_is_playing:
                if sp.tweeted:
                    state  = 3
                    printed = False

                else:
                    state = 1
                    printed = False

            else:
                check_printed(printed, state)
                state = 4
                printed = True

        # Correction for falling out of state, (Not State 0 but also sp_obj is None)
        # Essentially resetting to the default state
        else:
            state = 0
            printed = False

        # Add a sleep(5) as to not spam either Api
        time.sleep(5)

# Verifing valid log file
try:
    testfile = open(sys.argv[1],"r")
except IOError:
    print("Invalid Log File!\nUsage: ./app.py <logfile>")
    raise

testfile.close()

# Enables Proper Logging of the program
try:
    mainLoop()
except Exception as e:
    with open(sys.argv[1], "a") as log:
        currTime = get_curr_time()
        tb = sys.exc_info()
        log.write("---------------------------------------------------------------------------\n")
        log.write("[{}] An Error has occured!: {}\n".format(str(currTime), repr(e)))
        traceback.print_tb(tb[2], file=log)
        log.write("--------------------------------END LOGFILE--------------------------------\n")
    raise
