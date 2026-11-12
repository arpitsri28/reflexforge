# Service Configuration

Configuration precedence is defaults < file < environment < CLI, with recursive object merging and
 isolated mutable ownership. Environment keys MAIL_ENABLED, MAIL_HOST and JOB_INTERVAL use typed parsing.
 A false mail flag suppresses deliveries; interval zero disables scheduled jobs. Invalid booleans and
 negative intervals raise ValueError. Two application instances cannot affect each other's configuration
 or mutate DEFAULTS. File/CLI inputs are typed dictionaries; environment values are strings.

Run the public suite: `python -m unittest discover -s tests -v`.
This repository uses the Python standard library and runs offline.
