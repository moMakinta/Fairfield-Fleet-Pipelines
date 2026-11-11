## Updates

This started as a behind-the-scenes project. I wasn't building it to show anyone,
I just wanted to get better at data engineering and the only way I learn is by
building something and breaking it a few times. I'm still improving, but so far,
so good.

What changed since the first version:

- The source files are now Excel workbooks (.xlsx) instead of CSV. That's how this
  kind of data normally arrives from a depot or a sales office, so it felt more
  realistic. It also gave me more trouble than I expected. Excel stores dates as
  numbers and saves 80.9 as 80.900000000000006, and both of those caught me out
  before I got the reader working.
- The truck GPS files were zipped (.csv.gz) to save space. I unzipped them. They
  are small enough, and now you can open them straight from GitHub.
- The GPS files and the Spark output are still CSV on purpose. Spark doesn't read
  Excel without extra setup, and a tracking system wouldn't export Excel anyway.

The bigger addition is a second pipeline for the same company: a daily weather
risk pipeline. It pulls weather for each depot and port from a public API, runs
on a schedule with Airflow, and flags days where wind, rain or heat would be a
problem for moving chemicals. This one was about learning the things the first
project didn't cover: scheduling, retries, loading only what's new, and
backfilling history. I spent a lot more time on tests here than I did before.

There's still a list of known issues in the README and I've left it there. Some
of them I know how to fix now, some I'm still figuring out.
