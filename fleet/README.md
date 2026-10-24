# Your laptop as a site in the Brownout demo

The Mac runs Brownout. Your Windows laptop can join as one more "site": it measures its own power with its
battery, does real work, and stops or starts that work when the Mac's plan says so. The utility's power cap
then covers the Mac and every laptop together.

You need: a Windows laptop, Python 3.10 or newer, the repo, and the same Wi-Fi as the Mac. Nothing else is
installed. The program uses only Python's own standard library.

## 1. Can your laptop measure itself? (2 minutes, once)
1. Unplug the charger. The battery only reports its power while the laptop runs on battery.
2. Open PowerShell in the repo folder and run `git pull`, then:
   `powershell -ExecutionPolicy Bypass -File fleet\battery_probe.ps1`
3. The last line says GOOD, SLOW, NO READING, PLUGGED IN or UNCLEAR. Send the lines from `== SUMMARY` down
   to Aryen. Only a GOOD laptop can join.

## 2. Join (machine 1 first adds your laptop to `config/fleet.yaml` and tells you its site name)
1. Get Python if `python --version` does not work: install it from python.org (tick "Add python.exe to PATH").
2. `git pull` in the repo folder.
3. Get the Mac's address from Aryen. It looks like `http://10.0.6.240:8080`.
4. Measure your laptop once, unplugged, about a minute and a half (the fan may spin up):
   `python fleet\agent.py --mac http://<mac address>:8080 --site <your site name> --calibrate`
   It ends with "sent to the Mac: stored".
5. Join, still unplugged:
   `python fleet\agent.py --mac http://<mac address>:8080 --site <your site name>`
   One line keeps updating: the time, your laptop's watts, and whether its job is running or paused.
   Leave it running. The Mac decides when your laptop works.
6. To stop: Ctrl-C. Your laptop's job also pauses by itself if it cannot reach the Mac for 10 seconds.

## If something is wrong
- "plugged in": unplug the charger.
- "no answer from the Mac": check that you are on the same Wi-Fi as the Mac and the address is right. Venue
  Wi-Fi sometimes blocks laptops from reaching each other. A phone hotspot that both join fixes it.
- "is not a site in config/fleet.yaml": the site name is wrong, or machine 1 has not added your laptop yet.

## What is measured, honestly
Your laptop's watts are its battery's own discharge reading (Windows reports it in milliwatts). That is the
whole laptop, screen included, unlike the Mac's chip-only reading from powermetrics. The dashboard says which
meter each number comes from. The job is real work: lzma compression of your laptop's own Python standard
library. Its output is thrown away, but every megabyte is really compressed.
