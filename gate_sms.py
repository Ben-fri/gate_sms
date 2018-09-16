# -*- coding: utf-8 -*-

"""
This doesn't destroy the list. Instead it keeps a record of those which are already processed, so that they don't get
duplicate messages.

Now changed from smsGateway.me to sms4geeks.appspot.com
Changed again to allow either using "method" variable.
 to send through real phones. List of phones is in volunteers.txt
;name,prefix,deviceID,email,password,phone number, limit/day, expiry, custom message, time-window
  add to volunteer object: today_count, alltime_count, last_sent, interval
Ben,+44,47083,support@staysavr.com,rachel6075,+447780708780,100,2017-12-31,"custom,message",09:00,21:30
  
04/06/18: The input file, previously sms_marketing.txt has been split so that we don't send to Big Island owners at present.
The current input file is non_big_island.txt    The others are waiting in big_island.txt
 """
import time, os.path, csv, sys, datetime
import datetime, threading, csv, re
import glob
import urllib2
import json
import gspread
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.tools import run_flow
from oauth2client.tools import argparser
from oauth2client.file import Storage

global today_count, alltime_count, last_sent
global sheets, sc
global customRows
customrows = ''

method = "gisa"  # smsgateway or sms4geeks or gisa
"""# note: gisa runs a webserver on the phone so it has a LOCAL ip address and can only be accessed that way.
# use it in conjunction with freeDNS app, so that it can be accessed from far away using a domain name?
# The problem with that approach is it needs NAT settings on the router.

So, for gisa method, the program runs on PC that is local to the phone. 
Google API key: My Project-d1f58207eb05.json saved on my computer
    https://console.developers.google.com/iam-admin/serviceaccounts?project=angelic-tracer-206309&authuser=3

client ID: 388474423779-hcp52gjjh0n5tnlqas769tf9df6e1e43.apps.googleusercontent.com
Client secret: gXTFLY77I7qeP8vHbBwxIm1Z
    
Original use of google sheets was to update the sheet 1 with Message# sent. Update Sheet 2 with messages sent list, Sheet 
3 with messages received
Sheet 4 is to enable operators to send replies through the same phone.
"""

testing = 0  # If 3, it tries the custom send only
zones = {"+1": "USA", "+39": "Italy", "+44": "UK", "+33": "France", "+34": "Spain", "+49": "Germany",
         "+351": "Portugal", "+5": "South America", "+6": "Aus/NZ", "+7": "Russia", "+8": "East Asia",
         "+9": "West Asia", "+2": "Africa", "+3": "Southern Europe", "+4": "Northern Europe"}
zonekeys = zones.keys()
zonekeys.sort(lambda x, y: cmp(len(y), len(x)))

global processed, targets, blocks, cycles

cycles = -1

blocks = {}

# def save(phones):
#    with open("volunteers.txt", 'wb') as outfile:
#        writer = csv.writer(outfile, delimiter=',')
#        for p in phones:
#            writer.writerow(p)    
global testmode


def timediff(t1, t2):
    t1 = datetime.datetime.combine(datetime.datetime.today(), t1)
    t2 = datetime.datetime.combine(datetime.datetime.today(), t2)
    return t1 - t2


def main():
    global processed, targets, blocks, testmode, message
    global today_count, alltime_count, last_sent

    testmode = False

    if len(sys.argv) > 1: testmode = "test" in sys.argv
    if testmode:
        print "We are in test mode. No SMS will be sent and the sms_processed file will not be affected."
        print "The test mode messages will count against the quota for each phone!"
        print ""
    print "Using phone's IP address from environment variable: GISA"
    print "uses volunteers.txt file to control sending"
    print "use 'test' and/or 'single' for testing and single message modes"
    sentcount = 0
    blockfiles = glob.glob("*block.txt")
    for bf in blockfiles:
        prefix = bf[:bf.find("bl")]
        print "Processing block list for prefix: +" + prefix
        blocks["+" + prefix] = open(bf, "r").read().split("\n")

    processed = ""

    if "gisa" in method:

        gisaurl = os.environ["GISA"]

        if not gisaurl:
            print "I have no IP address for the phone, so I give up."
            sys.exit()
        if not gisaurl.count('.')>2:
            print "That's not a proper IP address for GISA"
            sys.exit(1)
        if not ":" in gisaurl: gisaurl += ":8080"
        if not gisaurl.startswith("http"): gisaurl = "http://" + gisaurl
    with open("gisa.txt", "w") as outfile:
        outfile.write(gisaurl)

    credentials = ""
    credentials = sheets_init(credentials)
    get_persistent(credentials)

    if testing == 3:
        custom_sending(gisaurl, credentials)
        print "Done"
        sys.exit()

    if testing == 1:
        test_response(gisaurl, credentials)
        sys.exit()

    # if os.path.isfile("sms_processed.txt"):
    #    processed =  open("sms_processed.txt","r").read()

    try:
        targets = open("non_big_island.txt", "r").read().split("\n")
        vfile = "volunteers.txt"
    except:
        targets = ['"Ben","+447780708780","Kaanapali","p175403"']
        vfile = "volunteers.test"

    print ("Using csv file: " + vfile)
    # read CSV file & load into list
    with open(vfile, 'rU') as my_file:
        reader = csv.reader(my_file, delimiter=',')
        phones = list(reader)
        # print phones
        print len(phones), "message instructions found."
    for p in phones:
        if len(p) < 6: phones.remove(p)
        while len(p) < 15: p.append("")


    finished = 0
    lc = -1

    # endless loop for phones
    while not finished:

        if "gisa" in method and not testmode: get_incoming(gisaurl, credentials)  # 

        lc = lc + 1
        lc = lc % len(phones)
        phone = phones[lc]
        prefix = phone[1]
        device = int(phone[2])
        email = phone[3]
        password = phone[4]
        daylimit = safeint(phone[6])
        expiry = datetime.datetime.today()
        try:
            expiry = datetime.datetime.strptime(phone[7], "%Y-%m-%d")
        except:
            pass

        custom_message = phone[8]

        earliest = datetime.datetime.strptime(phone[9], "%H:%M").time()
        latest = datetime.datetime.strptime(phone[10], "%H:%M").time()

        interval = safeint(phone[14])

        # a new day perhaps?
        if not last_sent.date() == datetime.datetime.today().date():
            today_count = 0
            interval = False

        early = datetime.datetime.combine(datetime.datetime.today(), earliest)
        late = datetime.datetime.combine(datetime.datetime.today(), latest)
        # interval not been calculated yet?  Interval is in minutes.
        if not interval:
            interval = int(((timediff(latest, earliest)).seconds / 60) / daylimit)
            now = datetime.datetime.now()
            if today_count == 0 and now > early:
                # when starting the program in middle of the day, we can have a faster send rate to catch up.
                interval = int((timediff(latest, now.time()).seconds / 60) / daylimit)
            if not interval: interval = 1

        # decide on whether this sender is OK to send or cycle round to another sender
        if (datetime.datetime.now() - last_sent).seconds < interval * 60:
            print ".",
            time.sleep(20)
            continue
        if today_count >= daylimit:
            print ":",
            time.sleep(60)
            continue
        #  add time of day checks
        now = datetime.datetime.now()
        early = datetime.datetime.combine(datetime.datetime.today(), earliest)
        late = datetime.datetime.combine(datetime.datetime.today(), latest)
        if now < early or now > late:
            print "-",
            time.sleep(60)
            continue

        # This one is OK to send. Update his counts (now kept on google sheet)
        last_sent = datetime.datetime.now()
        today_count += 1
        alltime_count += 1

        to, name, line, location = get_next_target(prefix, custom_message)
        if to == "": break

        # could do with a mechanism to exit (set finished flag) when no more targets can be picked up for any phones

        if not to: continue

        # if "gateway" in method: gw = smsGateway.SmsGateway(email=email, password=password)

        if not custom_message:
            message = default_message(name, to, message)
        else:
            if len(custom_message) < 153:
                if name:
                    name = name[:12] + ", "
                message = encode_sms(name + custom_message)
            else:
                message = encode_sms(custom_message)

        message = message.replace("{placename}", location)
        if testmode:
            print "testing: " + email + "&password=" + password + "&msisdn=" + to + "&msg=" + urllib2.quote(message)
        if not testmode:
            if 1:  # try:
                # if "gateway" in method:
                #     gw.sendMessageToNumber(to, message, device, options={})
                # elif "gisa" in method:
                if "gisa" in method:
                    ustring = gisaurl + "/send.html?to=" + to + "&text=" + urllib2.quote(message)
                    # print ustring
                    done = 0
                    while not done:
                        try:
                            response = urllib2.urlopen(ustring).read()
                            done = 1
                        except:
                            done = 0
                            print "~",
                            time.sleep(25)
                    # print response
                    if not "sent succes" in response:
                        print response.text
                        sys.exit()
                else:
                    response = urllib2.urlopen(
                        "https://sms4geeks.appspot.com/smsgateway?action=out&username=" + email + "&password=" + password + "&msisdn=" + to + "&msg=" + urllib2.quote(
                            message))

            else:  # except Exception as e:
                print 'Failure.'
                print 'Error code: ', e.message
                sys.exit()
            html = response

        # sc = "Sent %d (#%d) "%(sentcount+1,len(processed.split("\n")))
        # print "Send",to,message[:25],device,sc
        print "Send", to, message[:25], device

        # rewrite the processed list
        # processed += line + "\n"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        to_sheet2(to, message, timestamp, credentials)
        save_persistent(credentials)

        sentcount += 1
        if "single" in sys.argv: break
        time.sleep(20.0)

    print "List of targets is exhausted"


def test_response(gisaurl, credentials):
    make_response(gisaurl, credentials)


def make_response(gisaurl, credentials):
    credentials = sheets_init(credentials)
    sheet = sheets.worksheet("Received")
    received = sheet

    rows = sheet.get_all_records(empty2zero=False, head=1, default_blank='')
    received = sheet
    sheet1 = sheets.worksheet("Sheet1")
    print('sheet contains', len(rows), "rows.")

    for i, r in enumerate(rows):  # Extract list of IDs from spreadsheet
        if r['PROCESSED']: continue
        if not r['FROM']: break
        # print "Found:", r['ID'], r['FROM'], r['MSG'], "row:",i

        # phone = str(r['FROM']) # not good enough. It loses the + in front of the number
        phone = sheet.acell('B' + str(i + 2), value_render_option='FORMATTED_VALUE').value
        print "Debug: phone=", phone
        msg = r['MSG'].encode('utf-8')  # new encoding

        row = find_in_column(phone[-9:], sheet1, 'B')
        if row > 0:
            received.update_acell('E' + str(i + 2), "pending")
            print "Process row:", row, "of sheet1"
            # append received message to any existing and note that it's an SMS reply
            try:
                existing = sheet1.acell('E' + str(row)).value
                if len(existing) > 0: existing = existing + "| "
                sheet1.update_acell('F' + str(row), "SMS")
                sheet1.update_acell('E' + str(row), existing + msg)
                existinghandling = sheet1.acell('J' + str(row)).value
                if len(existinghandling): existinghandling = " |" + existinghandling

                # Row number in Received sheet is i+2 to allow for headers
                status = intelligent_reply(phone, msg, row, sheet1, received)
                received.update_acell('E' + str(i + 2), status)

                sheet1.update_acell('J' + str(row), status + existinghandling)


            except:
                print "Problem Column B match - PLEASE REPORT THIS"

        else:
            print "Could not match phone number of incoming message", phone


def get_incoming(gisaurl, cred):
    global cycles, sheets, credentials

    credentials = sheets_init(cred)
    sheet = sheets.worksheet("Received")

    msglist = []

    cycles += 1
    if cycles % 20: return  # runs on first call then every 20th.
    # on the same frequency we do custom sending
    custom_sending(gisaurl, credentials)

    # collect incoming SMS
    ustring = gisaurl + "/read.html?format=json"
    # print ustring
    try:
        response = urllib2.urlopen(ustring)
        r = response.read().replace('\r', '').replace('\n', '')
        messages = json.loads(r)["messages"]
    except:
        print "Could not communicate with the phone. Please check it. Re-start the program if the phone's IP address has changed."
        messages = []
        # return

    ids = []
    for m in messages:
        msglist.append(
            [m["id"].encode('utf-8'), m["from"].encode('utf-8'), m["date"].encode('utf-8'), m["text"].encode('utf-8')])
        ids.append(m["id"])

    # now compare these messages against the ones already stored which are in a Google Sheet
    unmatched = []
    rows = sheet.get_all_records(empty2zero=False, head=1, default_blank='')

    sids = []
    counter = 0
    for r in rows:  # Extract list of IDs from spreadsheet
        if not r['ID']: break
        sids.append(str(r['ID']))
        counter += 1

    for m in msglist:
        if not m[0] in sids:
            # print "Compared: ", m[0], "with", sids
            unmatched.append(m)
    # print type(m[0]), type(sids[0])
    for u in unmatched:  # add empty rows to end of sheet
        # print u
        # print "Row: ",counter
        sheet.insert_row(u, index=counter + 2, value_input_option='RAW')
        counter += 1

    if len(unmatched) > 0:
        make_response(gisaurl, credentials)
    time.sleep(20.0)
    return


def intelligent_reply(phone, msg, row, sheet, received):  # sheet is the object for Sheet1

    negs = ["no ", "sold", "never", "stop", "sorry", "i don't", " off", "nope", "wrong number"]
    whos = ["who is this", "who this is", "who's this", "who are you", "who r u", "who r you", "do i know you", "what?",
            "only text", "what's up", "who's this", "SMS only", "only SMS"]
    poss = ['yes', 'ok', "i do", "please call", "call me", "phone me"]
    calls = ["please call", "call me", "phone me", "a call", "to call"]
    email = ['@']

    lcmsg = msg.lower()
    neg = phrasetest(negs, lcmsg)
    who = phrasetest(whos, lcmsg)
    pos = phrasetest(poss, lcmsg)
    em = phrasetest(email, lcmsg)
    call = phrasetest(calls, lcmsg)

    print "In intelligent_reply: neg,who,pos,em,call=", neg, who, pos, em, call

    # some may fit more than one message category
    if neg and not (who or pos or em):
        # just mark the message as not for processing
        sheet.update_acell('J' + str(row), "none")
        return "None"
    elif em:
        newmessage = "Thanks for responding. I will email you shortly! Thanks. josh.03081971@gmail.com"
        if addCustom(phone, newmessage):   return "to email"
        return "*"
    elif call:
        newmessage = "Thanks for responding and apologies for the unconventional way to make contact! I'll call you later. Thanks - Josh"
        if addCustom(phone, newmessage):    return "to call"
        return "*"

    elif (who or pos) and not neg:
        newmessage = "Thanks for responding and apologies for the unconventional way to make contact! I work for HawaiiChee.com - a new subscription site for Hawaii rentals (no booking fees). It would be great to get your property listed and we offer a 90% discount code: SEPT2018  It's quick too: simply import your listing from VRBO. I have a lot more to tell you about it but would need to do it by email. Thanks. josh.03081971@gmail.com"
        if addCustom(phone, newmessage): return "auto"
        return "*"

    return 'pending'


def addCustom(number, message):
    global customRows

    print "In addCustom for", number, message

    custom = sheets.worksheet("CustomSend")
    # if not customRows: # trouble with persisting the sheet rows is that new rows can be added by other people.

    customRows = custom.get_all_records(empty2zero=False, head=2, default_blank='')

    counter = 0
    for r in customRows:  # Extract list of IDs from spreadsheet
        if not r['Number']: break

        # check that this number hasn't already been sent a custom message
        if number in str(r['Number']): return False
        counter += 1
    if testmode:
        print "Would send message to", number, message
    else:
        custom.insert_row(["", number, message], index=counter + 3, value_input_option='RAW')

    return True


def phrasetest(phrases, msg):
    for p in phrases:
        if p in msg: return True
    return False


def custom_sending(gisaurl, cred):
    global credentials
    # Collects messages put onto spreadsheet by human and sends them
    credentials = sheets_init(cred)
    sheet = sheets.worksheet("CustomSend")
    rows = sheet.get_all_records(empty2zero=False, head=2, default_blank='')
    counter = 0
    for r in rows:  # Extract list of IDs from spreadsheet
        counter += 1
        if not r['Date sent']:
            me = r['Message'].decode("utf-8")
            nu = r['Number']
            if not nu or not me: return
            me = encode_sms(me)
            row = counter + 2
            nu = sheet.acell('B' + str(
                row)).value  # data from get_all_records is interpreted as a number and will lose any leading zero
            if "gisa" in method:

                ustring = gisaurl + "/send.html?to=" + nu + "&text=" + urllib2.quote(me)
                response = urllib2.urlopen(ustring).read()
                # print response
                if not "sent succes" in response:
                    print "Error in attempt to send custom message to ", nu, response.text
                    sys.exit()
                print "Sent: " + me + " to: " + nu
                # update spreadsheet
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                try:
                    sheet.update_acell('A' + str(row), str(timestamp))
                except:
                    # that worked well!
                    print "Failed to update cell A" + str(row) + " on Sheet 4"
                time.sleep(10)  # gives server on phone time to recover


def get_persistent(cred):
    global today_count, alltime_count, last_sent, credentials

    credentials = sheets_init(cred)
    sheet = sheets.worksheet("Persistent")
    today_count = safeint(sheet.acell('B2').value)
    alltime_count = safeint(sheet.acell('B3').value)
    last_sent = datetime.datetime.strptime(sheet.acell('B1', value_render_option='FORMATTED_VALUE').value,
                                           "%Y-%m-%d %H:%M")


def save_persistent(cred):
    global today_count, alltime_count, last_sent, credentials

    credentials = sheets_init(cred)
    sheet = sheets.worksheet("Persistent")
    try:
        sheet.update_acell('B2', today_count)
        sheet.update_acell('B3', alltime_count)
        sheet.update_acell('B1', last_sent.strftime("%Y-%m-%d %H:%M"))
    except:
        # that worked well!
        print "Failed to update cells on Sheet 5 with values: ", today_count, alltime_count
        sys.exit()


def to_sheet2(to, message, timestamp, cred):  # Updates Sheet 2 and Sheet 1
    # msg_sigs = ['with no','has no','Just','Fee-free','discuss','avoid','find']
    global credentials

    credentials = sheets_init(cred)
    sheet = sheets.worksheet("Sent")
    rows = sheet.get_all_records(empty2zero=False, head=1, default_blank='')

    sids = []
    counter = 0
    for r in rows:  # Extract list of IDs from spreadsheet
        if not r['Phone']: break
        counter += 1
    sheet.insert_row([to, message, timestamp], index=counter + 2, value_input_option='RAW')

    return


def getvalue(x):
    return x.value.decode("utf-8")


def find_in_column(value, sheet,
                   column):  # value is a string and we search for cell with value that endswith that string

    try:
        cell = sheet.find(re.compile(r'\d*' + str(value)))
        # print "Found 042901025 as ",cell.value, cell.row, cell.col, ord(column)-64
        if cell.col == ord(column) - 64:
            return cell.row
        return 0
    except:
        return 0


def default_message(name, number, msg):
    language = msg

    if len(language) < 308:
        if name: name = name + ", "
        message = encode_sms(name + language)
    else:
        message = encode_sms(language)
    return message


def get_next_target(prefix, message):
    global processed, targets
    msg_sigs = ['with no', 'has no', 'Just', 'Fee-free', 'discuss', 'avoid', 'find']

    sheet = sheets.worksheet("Sheet1")

    number = sheet.acell('B' + str(alltime_count), value_render_option='FORMATTED_VALUE').value
    name = sheet.acell('A' + str(alltime_count)).value
    location = sheet.acell('C' + str(alltime_count)).value
    prop = sheet.acell('D' + str(alltime_count)).value

    line = name + "," + number + "," + location
    m_id = -1
    for i, m in enumerate(msg_sigs):
        if m in message: m_id = i + 1
    # write data into column for Msg used
    try:
        sheet.update_acell('I' + str(alltime_count), str(m_id))
    except:
        print "Damnit. Failed to update Column I row ", alltime_count, "on sheet 1"

    return number, name, line, location


def encode_sms(s):
    s = s.replace(u'ö', chr(124))
    s = s.replace(u'ü', chr(126))
    s = s.replace(u'ä', chr(123))
    s = s.replace(u'é', chr(101))
    return s


def get_access():
    CLIENT_ID = '388474423779-tk17r66mbavu2t243707qnrtn7f47oeg.apps.googleusercontent.com'
    CLIENT_SECRET = 'bkLZKbDudeNwvZ-CGY5fUnmc'

    flow = OAuth2WebServerFlow(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope='https://spreadsheets.google.com/feeds https://docs.google.com/feeds',
        redirect_uri='urn:ietf:wg:oauth:2.0:oob',
        access_type='offline',  # This is the default
        prompt='consent'
    )

    storage = Storage('creds.data')
    flags = argparser.parse_args(args=[])
    credentials = run_flow(flow, storage, flags)
    return credentials


def sheets_init(credentials):
    global sheets

    if not credentials:
        credentials = get_access()

    file = gspread.authorize(credentials)  # authenticate with Google
    sheets = file.open_by_key("1PiJbKaaeUxk1FQZYOJUNogKcUWw8jRr8qtiASfmEwK0")  # open sheet

    return credentials


def safeint(s):
    try:
        return int(s)
    except:
        return 0


if __name__ == "__main__": main()
