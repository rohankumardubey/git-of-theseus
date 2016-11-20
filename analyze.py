from __future__ import print_function
import argparse, git, datetime, numpy, traceback, time, os, fnmatch
from matplotlib import pyplot
import seaborn, progressbar

parser = argparse.ArgumentParser(description='Analyze git repo')
parser.add_argument('--cohortfm', default='%Y', help='A Python datetime format string such as "%%Y" for creating cohorts (default: %(default)s)')
parser.add_argument('--interval', default=7*24*60*60, type=int, help='Min difference between commits to analyze (default: %(default)s)')
parser.add_argument('--ignore', default=[], action='append', help='File patterns that should be ignored (can provide multiple, will each subtract independently)')
parser.add_argument('--only', default=[], action='append', help='File patterns that have to match (can provide multiple, will all have to match)')
parser.add_argument('repos', nargs=1)
args = parser.parse_args()

repo = git.Repo(args.repos[0])
commit2cohort = {}
code_commits = [] # only stores a subset
master_commits = []
commit2timestamp = {}
cohorts_set = set()
exts_set = set()

print('Listing all commits')
bar = progressbar.ProgressBar(max_value=progressbar.UnknownLength)
for i, commit in enumerate(repo.iter_commits('master')):
    bar.update(i)
    cohort = datetime.datetime.utcfromtimestamp(commit.committed_date).strftime(args.cohortfm)
    commit2cohort[commit.hexsha] = cohort
    cohorts_set.add(cohort)
    if len(commit.parents) == 1:
        code_commits.append(commit)
        last_date = commit.committed_date
        commit2timestamp[commit.hexsha] = commit.committed_date

print('Backtracking the master branch')
bar = progressbar.ProgressBar(max_value=progressbar.UnknownLength)
i, commit = 0, repo.head.commit
last_date = None
while True:
    bar.update(i)
    if not commit.parents:
        break
    if last_date is None or commit.committed_date < last_date - args.interval:
        master_commits.append(commit)
        last_date = commit.committed_date
    i, commit = i+1, commit.parents[0]

def get_entries(commit):
    return [entry for entry in commit.tree.traverse()
            if entry.type == 'blob'
            and all([fnmatch.fnmatch(entry.path, pattern) for pattern in args.only])
            and not any([fnmatch.fnmatch(entry.path, pattern) for pattern in args.ignore])]

print('Counting total entries to analyze')
entries_total = 0
bar = progressbar.ProgressBar(max_value=len(master_commits))
for i, commit in enumerate(reversed(master_commits)):
    bar.update(i)
    n = 0
    for entry in get_entries(commit):
        n += 1
        _, ext = os.path.splitext(entry.path)
        exts_set.add(ext)
    entries_total += n

def get_file_histogram(commit, path):
    h = {}
    try:
        for old_commit, lines in repo.blame(commit, path):
            cohort = commit2cohort[old_commit.hexsha]
            h[cohort] = h.get(cohort, 0) + len(lines)
            if old_commit.hexsha in commit2timestamp:
                h[old_commit.hexsha] = h.get(old_commit.hexsha, 0) + len(lines)
            _, ext = os.path.splitext(path)
            h[ext] = h.get(ext, 0) + len(lines)
    except KeyboardInterrupt:
        raise
    except:
        traceback.print_exc()
    return h

curves = {}
ts = []
file_histograms = {}
last_commit = None
commit_history = {}
print('Analyzing commit history')
bar = progressbar.ProgressBar(max_value=entries_total)
entries_processed = 0
for commit in reversed(master_commits):
    t = datetime.datetime.utcfromtimestamp(commit.committed_date)
    ts.append(t)
    changed_files = set()
    for diff in commit.diff(last_commit):
        if diff.a_blob:
            changed_files.add(diff.a_blob.path)
        if diff.b_blob:
            changed_files.add(diff.b_blob.path)
    last_commit = commit
    
    histogram = {}
    entries = get_entries(commit)
    for entry in entries:
        bar.update(entries_processed)
        entries_processed += 1
        if entry.path in changed_files or entry.path not in file_histograms:
            file_histograms[entry.path] = get_file_histogram(commit, entry.path)
        for key, count in file_histograms[entry.path].items():
            histogram[key] = histogram.get(key, 0) + count

    for key, count in histogram.items():
        if key not in cohorts_set and key not in exts_set:
            commit_history.setdefault(key, []).append((commit.committed_date, count))

    for cohort in cohorts_set:
        curves.setdefault(cohort, []).append(histogram.get(cohort, 0))

    for ext in exts_set:
        curves.setdefault(ext, []).append(histogram.get(ext, 0))

print('drawing cohort plot...')
cohorts = sorted(cohorts_set)
y = numpy.array([curves[cohort] for cohort in cohorts])
pyplot.clf()
pyplot.stackplot(ts, y, labels=['Code added in %s' % c for c in cohorts])
pyplot.legend(loc=2)
pyplot.ylabel('Lines of code')
pyplot.savefig('cohorts.png')

print('drawing extension plot...')
exts = sorted(exts_set)
y = numpy.array([curves[ext] for ext in exts])
pyplot.clf()
pyplot.stackplot(ts, y, labels=exts)
pyplot.legend(loc=2)
pyplot.ylabel('Lines of code')
pyplot.savefig('exts.png')

print('drawing survival chart')
deltas = []
total_n = 0
for commit, history in commit_history.items():
    t0, orig_count = history[0]
    total_n += orig_count
    last_count = orig_count
    for t, count in history[1:]:
        deltas.append((t-t0, count-last_count, 0))
        last_count = count
    deltas.append((time.time() - t0, -last_count, -orig_count))

deltas.sort()
total_k = total_n
xs = []
ys = []
for t, delta_k, delta_n in deltas:
    if t > 3 * 365.25 * 24 * 60 * 60:
        break
    xs.append(t / (365.25 * 24 * 60 * 60))
    ys.append(100. * total_k / total_n)
    total_k += delta_k
    total_n += delta_n

pyplot.clf()
pyplot.plot(xs, ys)
pyplot.xlabel('Years')
pyplot.ylabel('%')
pyplot.ylim([0, 100])
pyplot.title('% of commit still present in code base over time')
pyplot.savefig('survival.png')
