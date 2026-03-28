"""Single source of truth for the managed Miniforge condarc."""

CONDARC_TEMPLATE = """\
channels:
  - conda-forge
  - bioconda
channel_priority: flexible
remote_connect_timeout_secs: 30
remote_read_timeout_secs: 90
remote_max_retries: 5
show_channel_urls: true
auto_activate_base: false
"""

