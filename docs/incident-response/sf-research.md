# San Francisco grid incident response — research for the parked project (Oct 24, 2026)

Status: parked. Main is the compute dispatcher. Facts below are sourced; "unverified" is flagged.

## SF grid
- No utility-scale plant inside SF: Hunters Point closed May 2006, Potrero Jan 2011. Planned in-city CTs (SFERP): assume none (unverified).
- Trans Bay Cable: 400 MW, ±200 kV HVDC, Pittsburg → Potrero 115 kV, 53 mi, in service Nov 2010, Trans Bay Cable LLC (NextEra). About 40–60% of SF peak (Trans Bay Cable LLC 2016 GO-156 report to CPUC).
- One import corridor along Hwy 101: San Mateo → Martin (3150 Geneva Ave, Brisbane; OSM way 29399992).
  - 230 kV to Embarcadero (Fremont & Folsom).
  - 115 kV underground to Potrero (Illinois St, 22nd–23rd), Hunters Point (Jennings/Evans), Bayshore, Mission (8th & Mission) and Larkin (Larkin & Eddy).
  - Dec 8 1998: a San Mateo disturbance blacked out most of SF for ~8 h.
- SF peak: ~900–1,000 MW (1997/2000; no recent figure found).
- Hetch Hetchy Power (SFPUC): ~20% of city load (Muni, SFO, ZSFG, City Hall), delivered over PG&E wires.
- Live CAISO: DLAP_PGAE-APND, TH_NP15_GEN-APND via gridstatus. SF pnodes: resolve with CAISO().get_pnodes() (IDs unverified).

## Critical facilities
- Hospitals: from the CHHS/HCAI Licensed Healthcare Facility Listing CSV (COUNTY_NAME == "SAN FRANCISCO"); never hand-type coordinates.

  | Hospital | Licensed beds | Note |
  |---|---|---|
  | ZSFG | 397 | only Level I trauma |
  | UCSF Parnassus | 549 | |
  | UCSF Mission Bay | 289 | |
  | CPMC Van Ness | 292 | |
  | CPMC Mission Bernal | 98 | |
  | Kaiser SF | 239 | |
  | Saint Francis | 277 | |
  | St. Mary's | 267 | |
  | Chinese Hospital | 88 | |
  | SF VA | — | federal; not in state data |
- Data centers: 365 Main St (Digital Realty SFO12, 8.6 MW critical IT, operator spec); 200 Paul Ave (no public MW).

## Hero replay: Mission substation fire, Dec 20–23, 2025
- Timeline:

  | Time | Event |
  |---|---|
  | Dec 20, 1:04 PM | Outage begins |
  | ~1:49 PM | PG&E technician arrives |
  | 2:17 PM | SFFD called (>1 h after PG&E knew) |
  | ~3 PM | ~130k customers out at peak (counts of 120k–137k also reported) |
  | ~6:00–6:15 PM | Fire out |
  | 11 PM | ~95k restored |
  | Dec 21 | 21k, then 17k out |
  | Dec 22, 5 PM | 3.8k out |
  | Dec 23, 4:31 AM | All restored (PG&E Currents) |
- Effects: ~1,600 Waymo stoppages (city officials citing Waymo data); BART Powell and Civic Center closed; PG&E's AI restoration estimates were wrong. Credits: $200 per resident, ~$2,500 per business.
- Cause (Exponent, May 8, 2026): humidity and condensation caused an arc flash in an open-design 1940s building. Damage seen in November wasn't fixed and the fans had been broken for years. Third fire there (1996, 2003, 2025).
- Secondary replays: Larkin substation, Apr 21, 2017 (88k out, restored ~5 PM); CAISO EEA 3, Aug 14, 2020.

## Real response sequence
1. Detect: relays, SCADA, AMI last-gasp.
2. Make safe and notify the fire department. This lagged >1 h in 2025.
3. FLISR: PG&E runs it on 967 circuits, but it is weak on whole-substation loss and in the downtown network.
4. Essential customers: CPUC essential-use rules exempt hospital circuits from rotating outages. Hospitals: NFPA 110 Level 1, 10-s transfer, commonly Class 96; CMS 96-h planning.
5. Shed flexible load: Flex Alert → EEA 1/2 (demand response; AI compute fits here) → EEA 3 (rotating blocks, ~1–1.5 h each).
6. Crews by priority (5,500 storm crew on duty, Dec 2025).
7. Accurate ETAs.

## Feeds
- CAISO via gridstatus (keyless).
- Cal OES ArcGIS `Power_Outages_(View)/FeatureServer/0`, where=County='San Francisco' (keyless, 15-min refresh, 2,000 records per call).
- PG&E outage layer (see github.com/simonw/pge-outages).
- EIA-930 (free key).
- CHHS CSV; DataSF Socrata.
- OSM API bbox when Overpass is blocked.

## Not public, and how to show it honestly
- Not public: feeder topology, block-to-substation mapping, switch states, essential-customer lists, rotating-block maps, data-center curtailment contracts.
- Show as a "modelled service area" (Voronoi seeded at real substations, overlaid on the real outage polygons) and dashed modelled feeders, with a REAL/MODELLED badge on every layer and number.

## Positioning and open questions
- Incumbents: ADMS/FLISR from Schneider, GE Vernova, Siemens, Oracle. EPRI DCFlex (Microsoft is a member). Emerald AI: 25% for 3 h in Phoenix, May 3 2025.
- Lane: the Dec 2025 failures were coordination failures (fire call, hospital view, ETAs, flexible load, crews). Build decision support beside ADMS.
- Open: the thesis "the grid wasn't built for home EV charging, rooftop-solar backfeed and data centers → outages, surges, fires" needs its own sources before any pitch. The Dec 2025 fire was maintenance and humidity, not load growth.
- Automatic actions must come from a deterministic [the brief was cut off here; completed per CLAUDE.md non-negotiable 2:] engine, the solver of record, never from the LLM, which explains and negotiates only.

## Checked live on Sat Oct 24, 23:00 to 23:10 (machine 1, keyless public sources)
These close some of the "unverified" items above; the scratch lookups are not in the repo.
- Substations in OpenStreetMap (OSM API map call around each described location), all tagged operator PG&E:
  Mission way 35115839 (115/12/4 kV; OSM address 66 8th Street, not "1200 Mission"), Larkin way 71209428 (115/12 kV,
  Eddy St), Embarcadero ways 192883977 and 1154710859 (230 kV), Potrero Switchyard relation 14391219 (230/115 kV),
  Potrero Converter Station way 469210393 (200 kV, the Trans Bay Cable landing), Hunters Point way 1081705952
  (115 kV), Martin way 29399992 (230/115/60/12 kV). Bayshore: not in OSM by name; show it only on a schematic.
- In-city turbines: around Potrero, OSM maps no combustion plant; the one generator there is rooftop solar
  (way 1257566742). Keep "assume none", the worst case for SF.
- Hospitals, CHHS listing of 1 Oct 2026 (13 general acute care hospitals in SF): Kaiser SF is 2425 Geary Blvd
  (239 beds); CPMC Van Ness 292 and Mission Bernal 98 are the state license counts; Saint Francis is now licensed as
  UCSF Health Hyde Hospital (900 Hyde St, 277); ZSFG is the only "Emergency - Comprehensive" department. The listing
  also has 12 skilled nursing facilities (1,054 beds), essential under the same CPUC rule.
- Prices: all PG&E load settles at DLAP_PGAE-APND, so it is the right price for SF load, not a stand-in. CAISO's
  hub membership map (get_pnodes) has one node named after an SF substation, LARKIN12_7_LN001 (NP15); it priced live
  (day-ahead 24 Oct: mean $47.35/MWh against $45.62 at DLAP_PGAE). CAISO does not publish node locations: label it
  "named after Larkin". The "MISSION_*" nodes are in SP15 and "HUNTERP_*" in PacifiCorp East: not SF.
- SF peak: Trans Bay Cable LLC's 400 MW at 40–60 % of peak implies about 670–1,000 MW, consistent with 1997/2000.
- Dec 2025 customers: lead with "~130,000 (PG&E)" and drive any replay from PG&E's own restoration steps; footnote
  the 120k–137k range.
