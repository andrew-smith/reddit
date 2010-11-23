"""
Generate the data for the listings for the time-based Account
queries. The format is eventually that of the CachedResults objects
used by r2.lib.db.queries (with some intermediate steps), so changes
there may warrant changes here
"""

# to run:
"""
 psql -F"\t" -A -t -d newreddit -U ri -h $LINKDBHOST \
     -c "\\copy (select t.thing_id,
                        'link',
                        t.ups,
                        t.downs,
                        t.deleted,
                        t.spam,
                        extract(epoch from t.date),
                        d.value
                   from reddit_thing_link t,
                        reddit_data_link d,
                        reddit_data_account a
                  where t.thing_id = d.thing_id
                    and not t.spam and not t.deleted
                    and d.key = 'author_id'
                    and a.thing_id = cast(d.value as int)
                    and a.key = 'gold'
                    and t.date > now() - interval '1 year'
                ) to 'links.joined'"
cat links.joined | paster --plugin=r2 run $INI r2/lib/mr_gold.py -c "time_listings()" | sort -T. -S200m | paster --plugin=r2 run $INI r2/lib/mr_gold.py -c "write_permacache()"
"""
import sys

from r2.models import Account, Subreddit, Link
from r2.lib.db.sorts import epoch_seconds, score, controversy, _hot
from r2.lib.db import queries
from r2.lib import mr_tools
from r2.lib.utils import timeago, UrlParser
from r2.lib.jsontemplates import make_fullname # what a strange place
                                               # for this function


def time_listings(times = ('year','month','week','day','hour', 'all')):
    oldests = dict((t, epoch_seconds(timeago('1 %s' % t)))
                   for t in times if t != 'all')
    if 'all' in times:
        oldests['all'] = 0

    @mr_tools.dataspec_m_thing(('author_id', int),)
    def process(link):
        assert link.thing_type == 'link'

        timestamp = link.timestamp
        fname = make_fullname(Link, link.thing_id)

        if not link.spam and not link.deleted:
            author_id = link.author_id
            ups, downs = link.ups, link.downs

            sc = score(ups, downs)
            contr = controversy(ups, downs)
            h = _hot(ups, downs, timestamp)

            for tkey, oldest in oldests.iteritems():
                if timestamp > oldest:
                    yield ('user-top-%s-%d' % (tkey, author_id),
                           sc, timestamp, fname)
                    yield ('user-controversial-%s-%d' % (tkey, author_id),
                           contr, timestamp, fname)
                    if tkey == 'all':
                        yield ('user-new-%s-%d' % (tkey, author_id),
                               timestamp, timestamp, fname)
                        yield ('user-hot-%s-%d' % (tkey, author_id),
                               h, timestamp, fname)


    mr_tools.mr_map(process)

def store_keys(key, maxes):
    # we're building queries using queries.py, but we could make the
    # queries ourselves if we wanted to avoid the individual lookups
    # for accounts and subreddits.

    # Note that we're only generating the 'sr-' type queries here, but
    # we're also able to process the other listings generated by the
    # old migrate.mr_permacache for convenience

    if key.startswith('user-'):
        acc_str, sort, time, account_id = key.split('-')
        account_id = int(account_id)
        fn = queries.get_submitted
        q = fn(Account._byID(account_id), sort, time)
        q._replace([tuple([item[-1]] + map(float, item[:-1]))
                    for item in maxes])

def write_permacache(fd = sys.stdin):
    mr_tools.mr_reduce_max_per_key(lambda x: map(float, x[:-1]), num=1000,
                                   post=store_keys,
                                   fd = fd)
