import json
import oauth2
import urlparse
import xml.etree.ElementTree as ET
import httplib2

api_base = 'https://www.goodreads.com'
request_token_url = api_base + '/oauth/request_token'
authorize_url = api_base + '/oauth/authorize'
access_token_url = api_base + '/oauth/access_token'

creds = {}


def store_creds():
    localcreds = creds.copy()
    del localcreds["dev_key"]
    del localcreds["dev_secret"]
    with open("localcreds.json", mode="w") as lc:
        json.dump(localcreds, lc)


def login1():
    client = oauth2.Client(consumer)
    response, content = client.request(request_token_url, "GET")
    if response["status"] != "200":
        raise Exception("Setting up token failed: " +
                        response["status"] + "\n" + content)
    print "snagged prelim token"
    token = dict(urlparse.parse_qsl(content))
    key = token["oauth_token"]
    secret = token["oauth_token_secret"]
    creds["prelim_key"] = key
    creds["prelim_secret"] = secret
    store_creds()
    print("Please visit " + authorize_url + "?oauth_token=" + key)
    print("After authorizing this script, please restart it")


def login2(key, secret):
    token = oauth2.Token(key, secret)
    client = oauth2.Client(consumer, token)
    response, content = client.request(access_token_url, "POST")
    if response["status"] != "200":
        del creds["prelim_key"]
        del creds["prelim_secret"]
        store_creds()
        raise Exception("Grabbing access token failed: " +
                        response["status"] + "\n" + content)

    access_token = dict(urlparse.parse_qsl(content))
    key = access_token["oauth_token"]
    secret = access_token["oauth_token_secret"]
    creds["client_key"] = key
    creds["client_secret"] = secret
    store_creds()


def get_user_id(key, secret):
    token = oauth2.Token(key, secret)
    client = oauth2.Client(consumer, token)
    response, content = client.request(api_base + '/api/auth_user', 'GET')
    if response["status"] != "200":
        raise Exception("Grabbing user id failed: " +
                        response["status"] + "\n" + content)
    tree = ET.fromstring(content)
    user = tree.find(".//user")
    return user.attrib["id"]


def get_read_books(key, secret, user_id, page):
    url = (api_base + "/review/list?v=2&format=xml&sort=author&order=a" +
           "&per_page=20&shelf=read&id=" + user_id + "&key=" + dev_key +
           "&page=" + str(page))
    token = oauth2.Token(key, secret)
    client = oauth2.Client(consumer, token)
    response, content = client.request(url, "GET")
    if response["status"] != "200":
        raise Exception("Grabbing books failed: " +
                        response["status"] + "\n" + content)
    return content


def get_series_info(seriesid):
    url = (api_base + "/series/" + seriesid + "?format=xml&key=" + dev_key)
    h = httplib2.Http()
    print "grabbing " + url
    response, content = h.request(url, "GET")
    if response["status"] != "200":
        raise Exception("Grabbing series info failed: " +
                        response["status"] + "\n" + url + "\n" + content)
    tree = ET.fromstring(content)
    return ET.ElementTree(tree.find("./series"))


def get_series_for_work(workid):
    series = set()
    url = (api_base + "/work/" + workid +
           "/series?format=xml&key=" + dev_key)
    h = httplib2.Http()
    print "grabbing " + url
    response, content = h.request(url, "GET")
    if response["status"] != "200":
        raise Exception("Grabbing series for work failed: " +
                        response["status"] + "\n" + url + "\n" + content)
    tree = ET.fromstring(content)
    for seriesid in tree.findall(".//series/id"):
        series.add(seriesid.text)
    return series


def get_works_for_books(bookids):
    workids = []
    url = (api_base + "/book/id_to_work_id/" + ",".join(bookids) +
           "?key=" + dev_key)
    h = httplib2.Http()
    response, content = h.request(url, "GET")
    if response["status"] != "200":
        raise Exception("Converting books to works failed: " +
                        response["status"] + "\n" + url + "\n" + content)
    tree = ET.fromstring(content)
    for workid in tree.findall(".//work-ids/item"):
        workids.append(workid.text)
    return workids


def do_the_thing(key, secret):
    print "grabbing user"
    user_id = get_user_id(key, secret)
    print "user:", user_id
    page = 0
    book2work = dict()
    if True:
        bookids = []
        page += 1
        print "grabbing page %d for user %s" % (page, user_id)
        content = get_read_books(key, secret, user_id, page)
        tree = ET.fromstring(content)
        for review in tree.findall("./reviews/review"):
            bookid = review.find("book/id").text
            bookids.append(bookid)
            try:
                print(bookid + ": " + review.find("book/title").text)
            except UnicodeEncodeError:
                print(bookid + ": weird UTF8 shit")
#        if len(bookids) == 0:
#            break
        workids = get_works_for_books(bookids)
        book2work.update(dict(zip(bookids, workids)))
        print "%d books, %d works" % (len(bookids), len(workids))

    print book2work

    workids = set(book2work.values())

    seriesids = set()
    for workid in workids:
        couple = get_series_for_work(workid)
        print couple
        seriesids.update(couple)

    print len(seriesids)

    series = {}

    for seriesid in seriesids:
        series[seriesid] = get_series_info(seriesid)

    for s in series.values():
        read = []
        unread = []
        print "Series ID: " + s.find("./id").text
        print "Series title: " + s.find("./title").text.strip()
        for work in s.findall("./series_works/series_work"):
            workid = work.find("./work/id").text
            if workid in workids:
                read.append(work)
            else:
                unread.append(work)
        print "Read:"
        for work in read:
            pos = work.find("./user_position").text
            if pos is None:
                pos = "N/A"
            print "  " + pos + ": " + work.find("./work/best_book/title").text
        print "Unread:"
        for work in unread:
            pos = work.find("./user_position").text
            if pos is None:
                pos = "N/A"
            print "  " + pos + ": " + work.find("./work/best_book/title").text
        print "============================================="


with open("creds.json") as credsfile:
    print "Reading developer credentials from creds.json"
    creds.update(json.load(credsfile))

try:
    with open("localcreds.json") as credsfile:
        print "Reading client credentials from localcreds.json"
        creds.update(json.load(credsfile))
except:
    print "no local creds yet"

dev_key = creds["dev_key"]
dev_secret = creds["dev_secret"]

consumer = oauth2.Consumer(key=dev_key, secret=dev_secret)

client_key = creds.get("client_key")
client_secret = creds.get("client_secret")
prelim_key = creds.get("prelim_key")
prelim_secret = creds.get("prelim_secret")

if client_key is not None and client_secret is not None:
    do_the_thing(client_key, client_secret)
elif prelim_key is not None and prelim_secret is not None:
    login2(prelim_key, prelim_secret)
    client_key = creds.get("client_key")
    client_secret = creds.get("client_secret")
    do_the_thing(client_key, client_secret)
else:
    login1()

print "Done!"
