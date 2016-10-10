import json
import oauth2
import urlparse
import xml.etree.ElementTree as ET
import httplib2
import jinja
import re
import progressbar
from collections import defaultdict
import tempfile
import os
import webbrowser
import argparse


class Series:
    def __init__(self):
        self.sid = ""
        self.title = ""
        self.description = ""
        self.read_books = []
        self.unread_books = []
        self.unneeded_books = []
        self.authors = defaultdict(int)


class Book:
    def __init__(self):
        self.title = ""
        self.bookid = ""
        self.pos = ""
        self.image_url = ""
        self.rating = 0
        self.description = ""


api_base = 'https://www.goodreads.com'
request_token_url = api_base + '/oauth/request_token'
authorize_url = api_base + '/oauth/authorize'
access_token_url = api_base + '/oauth/access_token'

creds = {}

# "3-6" "1-4 omnibus"
posrange = re.compile(u"^(\d+)[-\u2013](\d+)(:? omnibus)?$")

# position strings we weren't able to deal with
unmatched_pos = set()

# for dev runs
max_books = None


def pos_to_set(inpos):
    inpos = inpos.strip().replace("#", "")

    if inpos == "N/A":
        return None

    # Try int before float, so that the resulting string is "3" not "3.0"
    try:
        pos = int(inpos)
        return set([pos])
    except:
        pass

    try:
        pos = float(inpos)
        return set([pos])
    except:
        pass

    m = posrange.match(inpos)
    if m:
        return set(range(int(m.group(1)), int(m.group(2)) + 1))

    for sep in ["&", ","]:
        if sep in inpos:
            sets = map(pos_to_set, inpos.split(sep))
            if None in sets:
                return None
            return reduce(set.union, sets)

    unmatched_pos.add(inpos)
    return None


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
    return user.attrib["id"], tree.find(".//name").text


def get_read_books(key, secret, user_id, page, per_page):
    url = (api_base + "/review/list?v=2&format=xml&sort=author&order=a" +
           "&shelf=read&per_page=" + str(per_page) + "&id=" + user_id +
           "&key=" + dev_key + "&page=" + str(page))
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
    response, content = h.request(url, "GET")
    if response["status"] != "200":
        raise Exception("Grabbing series info failed: " +
                        response["status"] + "\n" + url + "\n" + content)
    print content
    tree = ET.fromstring(content)
    return ET.ElementTree(tree.find("./series"))


def get_series_for_work(workid):
    series = set()
    url = (api_base + "/work/" + workid +
           "/series?format=xml&key=" + dev_key)
    h = httplib2.Http()
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
    user_id, user_name = get_user_id(key, secret)
    print "user:", user_id
    page = 0
    total_books = 0
    works_with_ratings = dict()
    per_page = 100  # docs say 200 max, but being safe
    while max_books is None or total_books < max_books:
        bookids = []
        ratings = []
        page += 1
        if max_books and (max_books - total_books) < per_page:
            per_page = max_books - total_books
        print "grabbing page %d of read books" % page
        content = get_read_books(key, secret, user_id, page, per_page)
        tree = ET.fromstring(content)
        for review in tree.findall("./reviews/review"):
            bookid = review.find("book/id").text
            bookids.append(bookid)
            rating = review.find("rating").text
            ratings.append(rating)
        num_grabbed = len(bookids)
        total_books += num_grabbed
        if num_grabbed == 0:
            break

        workids = get_works_for_books(bookids)
        for workid, rating in zip(workids, ratings):
            r = works_with_ratings.get(workid)
            rn = int(rating)
            if r:
                if rn > r:
                    works_with_ratings[workid] = rn
            else:
                works_with_ratings[workid] = rn

    workids = set(works_with_ratings.keys())
    seriesids = set()

    bar = progressbar.ProgressBar(widgets=[
        "Looking which series books are in",
        progressbar.widgets.SimpleProgress(
            format=" [%(value)d/%(max_value)d] "),
        progressbar.Bar(), ' (', progressbar.ETA(), ') ',
    ])

    for workid in bar(workids):
        seriesids.update(get_series_for_work(workid))

    series = {}

    bar = progressbar.ProgressBar(widgets=[
        "Grabbing series info",
        progressbar.widgets.SimpleProgress(
            format=" [%(value)d/%(max_value)d] "),
        progressbar.Bar(), ' (', progressbar.ETA(), ') ',
    ])

    for seriesid in bar(seriesids):
        series[seriesid] = get_series_info(seriesid)

    results = []

    for st in series.values():
        s = Series()
        tbd = []

        s.sid = st.find("./id").text
        s.title = st.find("./title").text.strip()
        s.description = st.find("./description").text.strip()
        authors = defaultdict(int)
        for work in st.findall("./series_works/series_work"):
            workid = work.find("./work/id").text
            book = Book()
            book.pos = work.find("./user_position").text
            book.rating = works_with_ratings.get(workid)
            if not book.rating:
                book.rating = 0
            if book.pos is None:
                book.pos = "N/A"
            book.bookid = work.find("./work/best_book/id").text
            book.title = work.find("./work/best_book/title").text
            book.author = work.find("./work/best_book/author/name").text
            book.image_url = work.find(
                "./work/best_book/image_url").text.strip()
            authors[book.author] += 1
            if workid in workids:
                s.read_books.append(book)
            else:
                tbd.append(book)
        s.authors = ", ".join(sorted(authors, key=authors.get, reverse=True))

        if len(s.read_books) == 1:
            rating = s.read_books[0].rating
            if rating > 0 and rating < 3:
                continue
        read = set()
        for book in s.read_books:
            posset = pos_to_set(book.pos)
            if posset:
                read.update(posset)
        for book in tbd:
            posset = pos_to_set(book.pos)
            if posset and posset <= read:
                s.unneeded_books.append(book)
            else:
                s.unread_books.append(book)
        results.append(s)

    results.sort(key=lambda x: (x.authors.split(", ")[0].split(" ")[-1],
                 x.authors, x.title))

    env = jinja.Environment(loader=jinja.FileSystemLoader(
        './templates'))

    tmpl = env.get_template("output.html")
    fd, path = tempfile.mkstemp(prefix="completeseries", suffix=".html")
    with os.fdopen(fd, "w") as f:
        html = tmpl.render(results=results, user_name=user_name)
        f.write(html.encode("utf-8"))
    webbrowser.open(path)


parser = argparse.ArgumentParser()
parser.add_argument('-m', '--max', type=int, default=None,
                    help="Maximum number of books to fetch")
args = parser.parse_args()
if args.max:
    max_books = args.max

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

print "Positions in series that are unparseable:"
up = set()
for pos in unmatched_pos:
    if "#" not in pos:
        up.add(re.sub("[0-9]", "#", pos))
    else:
        up.add(pos)
for pos in up:
    print "  " + pos

print
print "Done!"
