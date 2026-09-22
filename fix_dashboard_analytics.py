import re

fpath = 'C:/Users/Prasanna/Desktop/IB/backend/app/routes/dashboard.py'
content = open(fpath).read()

# Replace _build_file_query calls without scoped_user
content = re.sub(r'await _build_file_query\(file_id,\s*region_id,\s*country_id,\s*ib_version_id\)', 'await _build_file_query(file_id, region_id, country_id, ib_version_id, scoped_user=scoped_user)', content)

# Inject query = scoped_user.apply_to_query(query) right after
def insert_apply(m):
    match_str = m.group(0)
    return match_str + '\n    if scoped_user:\n        query = scoped_user.apply_to_query(query)'

content = re.sub(r'query = await _build_file_query\(file_id, region_id, country_id, ib_version_id, scoped_user=scoped_user\)', insert_apply, content)

open(fpath, 'w').write(content)
