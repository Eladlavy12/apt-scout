# Neighborhood knowledge base — sources and notes

`data/neighborhoods.json` holds one curated profile per polygon in
`data/neighborhoods.geojson` (68 neighborhoods + 3 city-level fallbacks).
Every profile lists the source keys below that informed it.

The `reputation` field answers one question only — **would a young professional
generally want to live here** — as the majority view across these sources. It is
not a price ranking and not a safety score. Where sources disagree the entry
says so in `summary`.

Research date: 2026-09-03.

## Sources

| key | what it is | url | fetched |
|---|---|---|---|
| `homemarket` | HomeMarket "מדריך השכונות של תל אביב — איפה אתם באמת" | https://homemarket.co.il/מדריך-השכונות-של-תל-אביב-איפה-אתם-באמת/ | 2026-09-03 — **HTTP 403, not fetchable**; not used |
| `secrettlv-2023` | Secret Tel Aviv FB group poll "סקר איפה הכי שווה לגור בתל אביב" | https://www.facebook.com/groups/secrettelaviv/posts/10161343037675943/ | 2026-09-03 — **not fetchable without login** (only the post title rendered); not used |
| `secrettlv-2019` | Secret Tel Aviv FB group thread "האזור הכי טוב למגורים בתל אביב" | https://www.facebook.com/groups/secrettelaviv/posts/10156576550365943/ | 2026-09-03 — **not fetchable without login** (only the post title rendered); not used |
| `quora-he` | Quora (he) "באיזו שכונה הכי כדאי לגור בתל אביב" | https://he.quora.com/באיזו-שכונה-הכי-כדאי-לגור-בתל-אביב | 2026-09-03 — **HTTP 403, not fetchable**; not used |
| `reddit-israel` | r/Israel "How is it like to live in Tel Aviv" | https://www.reddit.com/r/Israel/comments/ypxcgo/how_is_it_like_to_live_in_tel_aviv/ | 2026-09-03 — **reddit.com blocked for this fetcher** (old.reddit and `.json` too); not used |
| `diytlv` | DIY Tel Aviv Guide — Tel Aviv neighbourhood guide (long, candid, renter-focused) | https://www.diytelavivguide.com/blog/moving-to-tel-aviv/tel-aviv-neighbourhood-guide | 2026-09-03 |
| `wiki-he` | Hebrew Wikipedia articles, one per neighborhood (history, boundaries, building stock, population, socio-economic rank) | https://he.wikipedia.org/ | 2026-09-03 |
| `timeout-east` | Time Out (he) "ביצרון או התקווה? מדריך השכונות של מזרח תל אביב" — the single best consensus source for east TLV | https://timeout.co.il/השכונות-מזרח-תל-אביב/ | 2026-09-03 |
| `timeout-rg-gv` | Time Out (he) head-to-head "לאן תעזבו את תל אביב, לרמת גן או לגבעתיים?" (incl. 2022 rent figures) | https://timeout.co.il/ראש-בראש-ערי-לוויין/ | 2026-09-03 |
| `timeout-kfar-shalem` | Time Out (he) "כל מה שאתם צריכים לדעת על כפר שלם" | https://timeout.co.il/כפר-שלם/ | 2026-09-03 |
| `magdilim-east` | Magdilim "קרב השכונות של מזרח תל אביב" — Yad Eliyahu vs Nahalat Yitzhak, with rent ranges | https://magdilim.co.il/1302202091-2/ | 2026-09-03 |
| `themarker-east` | TheMarker "מזרח תל אביב" label — price per m², metro/light-rail, gentrification | https://www.themarker.com/labels/east-tel-aviv/ | 2026-09-03 |
| `walla-nadlan` | Walla Nadlan features on east and south-west TLV neighborhoods (Neve Hen, Park HaHorshot) | https://nadlan.walla.co.il/ | 2026-09-03 |
| `ynet-yad-eliyahu` | Ynet "הסינדרלה של ת"א: ביקור שכונה ביד אליהו" | https://www.ynet.co.il/articles/0,7340,L-4874464,00.html | 2026-09-03 |
| `ynet-rg-hoods` | Ynet "מלחמת שכונות בר"ג: איזו שכונה הכי שווה?" (socio-economic index and drive times per neighborhood) | https://www.ynet.co.il/articles/0,7340,L-4795505,00.html | 2026-09-03 |
| `hon-kfar-shalem` | Hon.co.il neighborhood ID card for Kfar Shalem (socio-economic 5/10, price per m², resident sentiment) | https://www.hon.co.il/שכונת-כפר-שלם-תל-אביב-תעודת-זהות/ | 2026-09-03 |
| `tlv-muni` | Tel Aviv-Yafo municipality planning and renewal pages (e.g. Kfir renewal, Central Station renewal) | https://www.tel-aviv.gov.il/Residents/Development/ | 2026-09-03 |
| `project-tlv` | Project TLV — neighborhood index and new-project lists per neighborhood | https://project-tlv.info/guides/neighborhoods/ | 2026-09-03 |
| `nta-lightrail` | NTA light-rail status: Red Line operating since 2023, Purple Line (Ramat Gan / Givatayim / east TLV) due 2026, Green Line ~2028 | https://www.nta.co.il/light-rail/ | 2026-09-03 (line pages themselves 403; status taken from the index and press coverage) |
| `nativeisrael` | Native Israel Tel Aviv neighborhoods guide — 2-bedroom rent figures per neighborhood | https://www.nativeisrael.com/blog/tel-aviv-neighborhoods | 2026-09-03 |
| `ronkin-2026` | Ronkin List "Best Tel Aviv Neighborhoods for Buyers and Renters 2026" | https://ronkin-list.com/tel-aviv-neighborhoods-2026/ | 2026-09-03 |
| `makler-bestworst` | Makler "Tel Aviv neighborhoods — the best and the worst" (blunt about Neve Shaanan / Shapira) | https://makler.co.il/en/tel-aviv-neighborhoods/ | 2026-09-03 |
| `alayof-2026` | Alayof Group "Tel Aviv Neighborhoods: real-estate price guide 2026" (price/m² tiers) | https://alayofgroup.com/blog/tel-aviv-neighborhoods-real-estate-price-guide-2026 | 2026-09-03 |
| `bizportal-borochov` | BizPortal "שכונת בורוכוב גבעתיים: הצעירים באים, הקרבה לתל אביב עולה ביוקר" | https://www.bizportal.co.il/realestates/news/article/813863 | 2026-09-03 |
| `pillu-givatayim` | Pillu "מדריך שכונות גבעתיים 2026 — איפה כדאי לגור ולקנות" | https://pillu.co.il/article-givatayim-neighborhoods-2026.html | 2026-09-03 |
| `calcalist-givatayim` | Calcalist on Givatayim's first master plan in 60 years: where pinui-binui and TAMA 38 are allowed | https://www.calcalist.co.il/articles/0,7340,L-3848913,00.html | 2026-09-03 |
| `maariv-weizmann` | Maariv HaMekomon "גבעתיים: המהפך של רחוב ויצמן" (Katznelson bar/café strip, Weizmann boulevard plan) | https://www.maariv.co.il/hamekomon/ramatgan/article-981865 | 2026-09-03 |
| `rg-muni` | Ramat Gan municipality — neighborhood pages and master-plan status map | https://www.ramat-gan.muni.il/my-neighborhood/ | 2026-09-03 |
| `nadlancenter-rg` | Merkaz HaNadlan "התחדשות עירונית רמת גן — המדריך השלם 2026" (RG holds ~1/5 of Israel's approved TAMA 38 projects; mostly demolish-and-rebuild) | https://www.nadlancenter.co.il/article/4298 | 2026-09-03 |
| `xnet-horshot` | Xnet on Park HaHorshot and the new Kiryat Shalom north-west district | https://xnet.ynet.co.il/articles/0,7340,L-4903921,00.html | 2026-09-03 |
| `madlan` | Madlan area-info pages (prices, schools, resident ratings) | https://www.madlan.co.il/ | 2026-09-03 |
| `hamichlol` | HaMichlol (Hebrew Wikipedia fork) neighborhood articles, used where he.wikipedia had no article | https://www.hamichlol.org.il/ | 2026-09-03 |
| `globes` | Globes real-estate coverage of Gush Dan urban renewal and the Central Station evacuation | https://www.globes.co.il/ | 2026-09-03 |
| `mako-xnet` | Mako / Xnet city and architecture features (Central Station area, Givatayim, Ramat Gan) | https://www.mako.co.il/ | 2026-09-03 |
| `en-wiki` | English Wikipedia neighborhood articles, used to cross-check names and boundaries | https://en.wikipedia.org/ | 2026-09-03 |
| `ynet-price-map` | Ynet "היקרות, הזולות והמפתיעות: מפת המחירים של השכונות בתל אביב" — price per m² for every TLV neighborhood, cheapest to dearest | https://www.ynet.co.il/economy/article/yokra14443171 | 2026-09-04 |
| `ynet-rentals` | Ynet ranking of the 128 most in-demand rental neighborhoods in Israel (Lev Tel Aviv 4th nationally; no Ramat Gan or Givatayim neighborhood in the top 20) | https://www.ynet.co.il/economy/article/yokra14886421 | 2026-09-04 |
| `ynet-kochav` | Ynet "מבוקשת ויקרה: הצצה לשכונת כוכב הצפון בת"א" | https://www.ynet.co.il/articles/0,7340,L-5266635,00.html | 2026-09-04 |
| `bizportal-kochav` | BizPortal on Kochav HaTsafon prices (~₪50k/m², still among the dearest in the city) | https://www.bizportal.co.il/realestates/news/article/20036084 | 2026-09-04 |
| `bizportal-rg` | BizPortal "סיור שכונות" series on Ramat Gan neighborhoods — Shikun Vatikim and HaRishonim, with building stock, demographics and prices | https://www.bizportal.co.il/realestates/news/article/813869 , https://www.bizportal.co.il/realestates/news/article/808493 | 2026-09-04 |
| `amiram-rg` | Amiram Oren's neighborhood-by-neighborhood cycling survey of Ramat Gan (founding dates, building stock and character for the neighborhoods with no Wikipedia article) | https://amiramorenbikes.com/2018_0307_ramatgan/ | 2026-09-04 |
| `citysquare` | CitySquare neighborhood urban-renewal reports (project counts, average build year, socio-economic cluster, prices) | https://www.citysquare.co.il/ramat-gan/ramat-shikma | 2026-09-04 |
| `maariv-bursa` | Maariv on the "משולש הבורסה" plan in Ramat Gan — ~950 units, ~400 of them long-term rentals at controlled rent, ~350 student rooms | https://www.maariv.co.il/business/realestate/Article-698382 | 2026-09-04 |
| `calcalist-barilan` | Calcalist on the Bar-Ilan campus jurisdiction split between Ramat Gan and Givat Shmuel (dorms and student centre moved to Givat Shmuel) | https://www.calcalist.co.il/real_estate/articles/0,7340,L-3850959,00.html | 2026-09-04 |
| `magdilim-jaffa` | Magdilim on municipality-led renewal in Yafo Alef (the College and Dakar area) and in Yafo Dalet | https://magdilim.co.il/200620241021/ | 2026-09-04 |
| `montefiore-renewal` | Coverage of the 2019 Montefiore master plan turning a garage district into mixed-use offices and housing | https://www.nadlancenter.co.il/article/14004 | 2026-09-04 |
| `timeout-noga` | Time Out on the Noga compound and north Jaffa — gentrification, boutiques, who moved in | https://timeout.co.il/porta-מתחם-נגה/ | 2026-09-04 |
| `tlvonline` | Tel Aviv Online neighborhood and price posts (Park Tzameret naming, Dakar's 810 new units, Kochav HaTsafon prices) | https://tlvonline.co.il/ | 2026-09-04 |
| `inference` | No usable published material found for the neighborhood; the profile is reasoned from the immediately surrounding area, the OSM polygon and the building stock, and says so in `summary` | — | 2026-09-03 |

### Sources that could not be fetched

Four of the six user-supplied links are not machine-readable:

- `homemarket` — HTTP 403 to this fetcher.
- `quora-he` — HTTP 403 to this fetcher.
- `reddit-israel` — reddit.com is blocked for this fetcher, including `old.reddit.com` and the `.json` endpoint.
- `secrettlv-2023` / `secrettlv-2019` — Facebook group posts return only the post title without a login; the titles confirm the threads are "סקר איפה הכי שווה לגור בתל אביב" and "האזור הכי טוב למגורים בתל אביב" but no answers rendered.

Their role — crowd consensus on "where is it actually good to live" — is covered
instead by `diytlv`, `timeout-east`, `timeout-rg-gv`, `makler-bestworst`,
`nativeisrael` and `ronkin-2026`. No profile cites a source that was not read.

## Rent reality (calibration for the ₪4,000–5,500 budget)

Useful for reading the profiles: the budget is for **2+ rooms Israeli count**
(living room included), i.e. roughly a one-bedroom.

- Tel Aviv city-wide average rent ≈ ₪7,200/month; the old north and the city
  centre sit far above it (`nativeisrael`: 2-bed ≈ ₪9,800 old north,
  ₪11,000+ Ramat Aviv, ₪8,500 Florentin).
- East TLV is where the budget actually lands: `magdilim-east` puts Yad Eliyahu
  3–4 rooms at **₪4,000–5,500**, and Nahalat Yitzhak at ₪5,775–7,000 for the
  same. `ynet-yad-eliyahu` (2016) had Yad Eliyahu 2-room at ≈₪3,300.
- South TLV: `nativeisrael` gives Shapira 2-bed ≈ ₪6,500 and HaTikva ≈ ₪5,800.
- Ramat Gan / Givatayim (`timeout-rg-gv`, Q1 2022): Ramat Gan 3-room ≈ ₪5,440,
  4-room ≈ ₪6,760; Givatayim 3-room ≈ ₪5,600, 4-room ≈ ₪7,380 — Givatayim is the
  most expensive city in the country after Tel Aviv and Herzliya.

## Transport facts used across the profiles

- **Red Line** light rail: operating since 2023. Underground through Ramat Gan
  (Bialik, Abba Hillel) and along Jerusalem Blvd in Jaffa; surface along
  Salame/Yehudit in south TLV. (`nta-lightrail`, `wiki-he`)
- **Purple Line**: runs from Yehud / Or Yehuda / Givat Shmuel through Ramat Gan
  and Givatayim into central Tel Aviv, with stations on the Yad Eliyahu /
  Wolfson Park / La Guardia axis — the single biggest change coming to the
  east-TLV neighborhoods. **Sources disagree on the opening date.** The NTA
  index page and the property coverage that leans on it (`walla-nadlan`,
  `themarker-east`) say **2026**; other coverage and the Hebrew Wikipedia line
  article put commercial opening at **2028**. The NTA line page itself returned
  HTTP 403 and could not be checked, and the follow-up search hit a rate limit.
  **Because of this the profiles deliberately name no year for the Purple Line**
  — they say a station is planned or under construction and leave the date out.
  Anyone re-reading this file should verify the date before adding one.
- **Green Line**: partial opening around 2028, with the underground stations
  later; it serves south-west TLV (Holon direction) and the new Park HaHorshot
  district. Same caveat — the profiles say "planned", not a year.
  (`nta-lightrail`, `xnet-horshot`)
- Heavy rail: HaShalom and Savidor stations flank Nahalat Yitzhak; HaHagana
  station serves Neve Shaanan / Shapira / HaTikva. (`magdilim-east`, `diytlv`)
- Givatayim and Ramat Gan run limited Saturday bus service ("Sababus" in Ramat
  Gan since 2019); most of Tel Aviv does not. (`wiki-he`)

## Notes by neighborhood

Notes are grouped by city. Only the facts that actually shaped a profile are
recorded; a neighborhood with no note under it is one where the profile rests on
`inference` plus the neighbouring areas, and its `summary` says so.

### גבעתיים

**borochov — בורוכוב.** Founded 1922 as the first workers' neighborhood in the
country; had the first cooperative grocery in the Yishuv (`wiki-he`). Today the
north-west corner of Givatayim, bordering Nahalat Yitzhak in Tel Aviv. Veteran,
quiet, green, dense; quiet residential streets with no major through-roads.
Housing stock skews **small** — most transactions are 40–60 m² units, which is
why it draws young professionals rather than families. Bars and small venues
have opened around it. Prices ≈₪44,000–46,000/m², with a ~3% correction lately;
rent for a whole apartment ≈₪8,500–9,000 — cheaper than Tel Aviv but not by
much. Central to Givatayim's urban-renewal activity, so buildings vary wildly in
condition. (`bizportal-borochov`, `pillu-givatayim`, `wiki-he`)

**givatayim_city — סיטי / מרכז העיר.** The commercial and nightlife core:
Katznelson, Sheinkin, Sirkin, Weizmann, Borochov streets plus the Givatayim
mall. Katznelson has become a genuine café/bar/restaurant strip pulling people
from outside the city; Weizmann is being upgraded with the long-term aim of
making it a boulevard on the Rothschild model, and Katznelson is getting bike
lanes and rapid-transit infrastructure. The 2020s master plan — the city's first
in 60 years — allows individual TAMA 38 here (and in Rambam and Arlozorov), and
a metro station is planned at Katznelson–Ben Gurion. Mixed building stock, so
price and quality range widely. (`maariv-weizmann`, `calcalist-givatayim`,
`pillu-givatayim`)

**givatayim (city-level).** OSM maps only two Givatayim neighborhoods, so most
Givatayim listings land on the city polygon. Givatayim as a whole: 57,920
residents, socio-economic cluster 9/10, the third-densest city in Israel
(≈17,900 people/km²) spread over four hills; first in the country for
matriculation eligibility (97.9%); historically an elderly city now visibly
getting younger. Consensus read: bourgeois, walkable, aesthetically pleasant,
family-oriented; expensive for what you get (most expensive rents in the country
after Tel Aviv and Herzliya), thin rental supply, and quiet in a way that can
feel limiting if you are single. Purple Line will serve it from 2026.
(`wiki-he`, `timeout-rg-gv`, `pillu-givatayim`, `nta-lightrail`)

### רמת גן

**ramat_gan (city-level).** 173,194 residents (2026), 92.6% Jewish, average wage
₪17,071 (2023) — well above the national ₪12,593. Markets itself as Israel's
greenest city (~25% green space). Red Line runs underground through the centre
(Bialik and Abba Hillel stations); Purple Line adds Tel HaShomer / Bar-Ilan /
Aluf Sadeh from 2026; "Sababus" gives four Saturday routes toward Tel Aviv.
Ramat Gan is the national capital of urban renewal — roughly a fifth of Israel's
approved TAMA 38 projects, most of them demolish-and-rebuild — so scaffolding and
construction noise are a citywide fact, not a per-neighborhood one. Consensus:
economically the sensible alternative to Tel Aviv; architecturally rougher and
less pretty than Givatayim, urban in parts and sleepy in others. Q1-2022 rents:
3-room ≈₪5,440, 4-room ≈₪6,760. (`wiki-he`, `timeout-rg-gv`, `nadlancenter-rg`,
`nta-lightrail`)

**ramat_amidar — רמת עמידר.** East Ramat Gan against Highway 4, bordering Bnei
Brak to the north. Built 1950 as two-storey "בתי תותח"; first residents were
Holocaust survivors and immigrants from Yemen and Egypt, and the area was
briefly seen as a luxury neighborhood before being reclassified a workers'
neighborhood in 1953 amid complaints of neglected sanitation and street
lighting. Rehabilitated in the late 1970s; the Bulgarian quarter has been almost
entirely replaced by dense high-rise. ~8,700 residents (2017). Named in the
municipality's neighborhood-by-neighborhood renewal planning. (`wiki-he`,
`rg-muni`)

**ramat_efal — רמת אפעל.** Far eastern Ramat Gan in the Ono valley, on the land
of the dissolved Kibbutz Efal; developed from 1969 as villas and cottages, with
2–3 storey houses added through 1997. Was an independent community settlement
with its own local council until it was folded into Ramat Gan in 2008. ~2,800
residents. Suburban, car-dependent, nothing urban about it. (`wiki-he`)

**azor_habiluim — אזור הבילויים.** South Ramat Gan. Socio-economic 6–7/10,
average wage ≈₪10,300, some of the best schools in the city, generous green and
open space — and explicitly described as cut off from Ramat Gan's own
entertainment centres. ~22 minutes to Azrieli, 15 to the Aluf Sadeh interchange.
(`ynet-rg-hoods`)

**haruzim — חרוזים.** Has turned trendy with young people, students and
families, on the strength of being right against Tel Aviv and Yarkon Park.
(`timeout-rg-gv`)

### תל אביב יפו

**tel_aviv_yafo (city-level).** Used when a listing falls inside the city but
outside every mapped neighborhood polygon. City-wide average rent ≈₪7,200; the
east and south are the cheap entry points and carry most of the renewal
pipeline, the old north and centre are the expensive end. (`nativeisrael`,
`alayof-2026`, `ronkin-2026`)

**orot — אורות.** The reference point (ORT Singalovski college) is inside this
polygon. East TLV, east of Yad Eliyahu, district 9; formally a sub-neighborhood
of Kfar Shalem, and it only got its current name in January 2011. Tiny: about
**300 households**. Socio-economic ≈13/20, 9.8% with academic degrees, and a
**median age of 65 — the highest of any neighborhood in the city**. ORT
Singalovski college sits inside it. Time Out's east-TLV guide lists it among the
Kfar Shalem sub-neighborhoods rather than treating it separately.
(`wiki-he`, `timeout-east`, `project-tlv`)

**yad_eliyahu — יד אליהו.** Established 1945 for demobilised British Army
veterans; the municipality funded hundreds of one-room flats. Now the city's
largest neighborhood by area with ~15,500 residents and ~6,500 households,
mostly 1950s public housing — single-family houses and "רכבת" blocks up to five
storeys, aging and in places neglected — with a few taller buildings. Menora
Mivtachim arena, Galit Park, La Guardia as the main axis. Socio-economic 6/10;
53% own their home but only 18% have degrees. The consensus positives are
consistent: quiet, family-oriented, large flats for the money, plenty of
parking, good buses and rail, and rents genuinely inside this budget
(₪4,000–5,500 for 3–4 rooms per `magdilim-east`; ₪3,300 for a 2-room back in
2016). The consensus negative is just as consistent: there is nowhere to sit —
almost no cafés or bars — and the buildings are old. Called TLV's "Cinderella";
Time Out less kindly calls it the code name for couples fleeing the centre at
40. Big changes coming: 2,400+ new units, a La Guardia densification plan, an
Afeka College campus for ~5,000 students on 14 dunams between La Guardia, Moshe
Dayan and HaHagana, student housing, and four Purple Line stations nearby.
(`wiki-he`, `ynet-yad-eliyahu`, `magdilim-east`, `themarker-east`, `timeout-east`,
`diytlv`)

**nahalat_yitzhak — נחלת יצחק.** Founded 1925 by middle-class immigrants from
Kaunas as a 400-dunam farming colony, named after Rabbi Yitzhak Elchanan
Spektor. ~7,500–8,400 residents on 556 dunams. Now wedged between Givatayim and
the Ayalon and often described as "the Givatayim of Tel Aviv" — pastoral and
quiet, with a strong community feel, 38% degree-holders, and rapid gentrification
(artisanal cafés replacing the old kiosks). Two heavy-rail stations, HaShalom and
Savidor, sit at its two ends; the Yigal Alon employment spine, the Bursa,
Azrieli and Ichilov are all close. Downsides: severe evening parking shortage,
already-high prices (rent ₪5,775–7,000 for 3–4 rooms — above this budget), and
33–40 storey mixed-use towers going up on the Alon axis. A weapons plant
operated here 1948–1997 and contaminated the groundwater; cleanup started in the
2020s ahead of residential building. (`wiki-he`, `magdilim-east`,
`themarker-east`, `timeout-east`)

**bitzaron_ramat_israel — ביצרון ורמת ישראל.** One polygon, two neighborhoods,
~4,950 residents on 698 dunams shared. Both sit on land that belonged to the
German Templers of Sarona and was confiscated in WWII. Bitzaron was built by the
Ezra U'Bitzaron housing company; its southern half is 1950s single-storey
municipal-employee duplexes, streets named for Haskalah figures. Ramat Israel
started in 1947 as emergency housing for people displaced by the fighting and was
renamed in 1959; small attached houses with little gardens, several
pedestrian-only streets. Long carried a bad name, then turned around from the
1990s once the small-house-with-garden format became desirable. Time Out calls
the pair "the Pardes Hana of east Tel Aviv" — hipster gentrification layered over
long-time residents, with Sderot Haskala carrying real charm; young families like
it. The western strip of Bitzaron is an employment zone where the old Amcor and
Argaz factories have been replaced by office towers zoned up to 50 storeys, plus
Central Park and the Electra Tower. (`wiki-he`, `timeout-east`)

**ramat_hatayasim — רמת הטייסים.** 1950s, named for three IAF pilots killed
defending Tel Aviv in 1948. Very small: ~134 dunams, 45 residential buildings of
two to three storeys with tiled roofs and gardens, ~2,050–2,200 residents, a
green tree-lined avenue running through to Wolfson Park. Borders Ramat Chen in
Ramat Gan. Time Out's phrase is "the polished pearl of the east" and the
comparison everyone reaches for is a moshav. A 2021 municipal policy document
proposed renewal. Commercial centre, Clalit clinic, a school; not much else.
(`wiki-he`, `timeout-east`, `nativeisrael`)

**tel_haim — תל חיים.** East TLV on the Givatayim border, east of the Ayalon and
Yad Eliyahu; ~4,400–4,500 residents on 370 dunams. Founded in the 1930s, barely
populated until the 1960s; was a Haganah front position and training base, and
the transmitter in an underground bunker here carried the Declaration of
Independence broadcast. Apart from a few multi-storey buildings at the entrance
it is almost all two-storey. Time Out reads it as deliberately self-isolating —
quietly more prestigious than Yad Eliyahu and unassuming about it — with the
well-regarded Etzioni religious state school. (`wiki-he`, `timeout-east`)

**hatikva — שכונת התקווה.** Founded 1935; Tel Aviv refused to annex it before
statehood, so residents built their own institutions. Sat as the buffer between
Tel Aviv and the Arab village of Salama and was attacked from there in December
1947. Demographically transformed twice: 92.3% Asia/Africa origin in 1979, down
to 48.3% by 1998 as Soviet and European immigrants arrived; more recently a
significant population of foreign workers and African asylum seekers. Time Out
calls it the neighborhood with the most character in the east — the best market
in the city, Adal's kebab, a football tradition, Ofra Haza's memorial in Gan
HaTikva, Beit Dani community centre — and names its real obstacle precisely: the
psychological barrier of crossing the Ayalon, which has slowed gentrification;
it also notes recent tensions inside the Eritrean community. Socio-economic
3/10, the lowest of its neighbours. `nativeisrael` puts a 2-bed at ≈₪5,800.
Adjacent Yad Eliyahu residents treat the market as an amenity and the
neighborhood south of it as run-down. (`wiki-he`, `timeout-east`, `diytlv`,
`nativeisrael`)

**ezra_haargazim — עזרא והארגזים.** One polygon, two neighborhoods, 765 dunams,
~2,700–3,100 residents. Ezra was founded by immigrants from Arab countries
before independence, growing south out of HaTikva; streets named after Hebrew
months and farming terms; the first Scud of the 1991 Gulf War landed here.
HaArgazim grew with no planning at all in the abandoned structures of Salama —
Yitzhak Rabin, visiting in 1993, said it looked like a refugee camp; no schools,
no sewage, unpaved lanes, and organised rubbish collection only from the 2000s.
Many residents have no legal title. Redevelopment has been rolling since 1998:
one 17-storey building, then eight "Park Tel Aviv" towers by Elad, then a January
2022 plan for 1,800 apartments in the north that displaces what is left of the
informal housing. Time Out is blunt: years of neglect, a sanitation facility whose
smell dominates daily life, long-time residents facing eviction, and Park Darom's
water-ski cable as the one attraction. (`wiki-he`, `timeout-east`)

**kfar_shalem (as neve_barbur_kfar_shalem_west / neve_eliezer_kfar_shalem_east).**
Built on the ruins of Salama (≈7,600 residents pre-1948, captured April 1948),
resettled with Yemenite immigrants from Operation Magic Carpet. 21,500–31,700
residents depending on how the sub-neighborhoods are counted, over ~1,587
dunams. Socio-economic 5/10; ~50% blue-collar, 55% without a matriculation
certificate; average flat ≈₪1.65–1.9M, ≈₪23,200/m², half the units 3-room. The
defining fact is unresolved land title: a 1965 evacuation-and-reconstruction law
started demolitions, a resident was killed during a forced eviction in 1982, and
~300 families still live in structures slated for demolition; light-rail
construction from 2018 reopened the compensation fight. Practical texture: 15
minutes to the centre by car, 30 by bus (39, 239), parking zone 30, parking
easier than the city average, abundant parks (Park Darom, Rosh HaKfar with its
fish pond, Ramat Gan National Park), Tel Chai rated among Israel's better
primary schools — and almost no shops, no bank branch, no pharmacy, and nowhere
to spend an evening. Peacocks, chickens and horses in the streets are a
recurring detail in every write-up. Sub-neighborhoods: Neve Kfir, Neve Tzahal,
Neve Barbur, Neve Eliezer, Neve Hen, Nir Aviv, Livna, Yedidya, Orot.
(`wiki-he`, `timeout-kfar-shalem`, `hon-kfar-shalem`, `timeout-east`)

**neve_eliezer_kfar_shalem_east — נווה אליעזר.** Built in the 1970s on the
Salama ruins. Was known as a drugs-and-crime centre; that reputation has eased
markedly over the last two decades and values have risen. A pinui-binui project
for ~320 units started in November 2020. Community centre with classes, sports
and a library. (`wiki-he`)

**neve_barbur_kfar_shalem_west — נווה ברבור.** 1970s, dense multi-storey blocks
unlike the low old Kfar Shalem core next to it; ~4,400 (2007) to ~4,950 (2012)
residents. Bounded by Derech HaHagana, Mahol St, Derech Moshe Dayan and Rabbi
Elankwa. The Beit Barbur country club (pools, tennis) and the bar next to it are
where the wider Kfar Shalem area actually socialises. (`wiki-he`,
`timeout-kfar-shalem`)

**neve_hen — נווה חן.** Sub-neighborhood of Kfar Shalem between Yad Eliyahu to
the east and Ramat HaTayasim / Ramat Chen to the west; ~6,000 residents;
socio-economic 5–6/10, low for Tel Aviv (Ramat Chen next door is 9/10, HaTikva
3/10). Everything hangs off one street, Ma'apilei Egoz: the southern stretch is
four-storey blocks, much of it now in TAMA 38 or pinui-binui with Groupit and
Azorim building; the northern stretch is eight-storey buildings ending in a
cul-de-sac and is quieter and more spacious. Buses 4 and 16, sherut on Saturday.
The **Purple Line's Wolfson Park station is due at the northern edge in 2026**.
Green: Shrani Park, Edith Wolfson Park, Begin Park. Two commercial centres with
supermarkets. Candid downsides from the same coverage: underdeveloped compared
to west TLV, none of the "Tel Aviv experience" people come for, and years of
construction disruption ahead. Renewal has accelerated since 2019 and brought in
young renting families. (`wiki-he`, `walla-nadlan`, `nta-lightrail`)

**neve_kfir — נווה כפיר / שכונת כפיר.** 253 dunams, ~3,120 residents (2012).
Until the 1970s this was Salama; the municipality moved residents out and built
new. Designed by architects Ora and Yaakov Yair with A. Hallel and awarded the
Rokach Prize in 1980: five blocks, each with ten four-storey buildings and one
eight-storey, curved around playgrounds, with a communal "core building" at the
centre — ~600 flats in total. Almost nothing has changed physically since. As of
late 2023 the municipality approved redevelopment of nearly all the original
buildings, keeping only the core building; the policy document (תא/מק/9100) came
out of six public meetings. (`wiki-he`, `tlv-muni`)

**nir_aviv, livna_yedidya — ניר אביב, לבנה וידידיה.** Kfar Shalem
sub-neighborhoods with no dedicated coverage; no Hebrew Wikipedia article for
either. Livna and Yedidya together: ~5,130 residents on 1,145 dunams (the figure
includes Park Darom). Yemenite-founded. Time Out records the specifics that
matter: they sit next to a sanitation facility, the Kfar stream crossings flood
Yedidya in winter, and the neighborhoods are neglected; the attractions are Begin
Park, Ariel Sharon Park and the petting zoo, i.e. things for children.
(`timeout-east`, `hon-kfar-shalem`, `inference`)

**park_darom — פארק דרום.** Mostly the park itself (Menachem Begin Park), opened
1988 as "South Park", ~1,000 dunams of which ~500 developed, designed by Zvi
Dekel; Israel's only cable water-ski facility, artificial lakes, a petting zoo, a
sledding slope, and a ~40-dunam wave pool completed April 2025. Managed by Ganei
Yehoshua. Bordered by the Mikveh Israel fields, Sha'ar HaArgazim and Kfar
Shalem, and meant eventually to join Ariel Sharon Park. The residential part is
the Sha'ar HaArgazim / "Park Tel Aviv" towers on the old HaArgazim land.
(`wiki-he`, `timeout-east`)

**neve_shaanan — נווה שאנן.** Founded 1921 by 400+ Jews fleeing the Jaffa
riots; laid out by Yosef Tishler as a menorah with Levinsky Street as the base.
Declined sharply in the 1990s after the new Central Bus Station opened in 1993 —
crime, deteriorated buildings, homelessness. Roughly **half the residents are
foreign workers or asylum seekers**. Every consensus source is unambiguous that
this is the roughest part of the city: `makler-bestworst` puts it bottom of the
list on crime; `diytlv` is specific that the real risk is harassment of women,
especially around Har Zion Blvd, more than physical violence, and equally
specific about what is good here — African, South-East Asian, Chinese and Indian
shops and restaurants that outsiders never find, cheaper rent than Florentin,
and the Central Station and HaHagana rail station on the doorstep. Signs of
change: Levinsky Garden (2007), a Bat Sheva campus due 2028, and — after years of
delay — an approved plan (April 2026) to move bus operations to a temporary
terminal near the Holon–Mikveh Israel junction and redevelop the 230-dunam
station site. (`wiki-he`, `diytlv`, `makler-bestworst`, `globes`, `mako-xnet`,
`tlv-muni`)

**shapira — שפירא.** Founded 1924 by Meir Getzl Shapira, a Detroit real-estate
dealer; Bukharan, Salonikan and Afghan immigrants first. Under Jaffa's
jurisdiction until 1948. ~11,000 residents on 820 dunams; a 2006 master plan
tackled the aging infrastructure. Today a genuine mix — religious traditional
families, secular residents, students, migrant communities — with young people
priced out of Florentin moving in. `diytlv` is the most honest source on it:
affordable, real community feel, narrow streets and small houses with gardens
and roof terraces, authentic workers' restaurants, near the Central Station and
HaHagana rail — against junkies, sex work, dark streets, municipal neglect,
shouting day and night, and the Har Zion Blvd strip in particular; it also says
plainly that it is not as dangerous as its reputation but does require street
smarts. `nativeisrael` puts a 2-bed at ≈₪6,500. `makler-bestworst` lists it among
the worst neighborhoods. (`wiki-he`, `diytlv`, `makler-bestworst`,
`nativeisrael`, `alayof-2026`)

**kiryat_shalom — קרית שלום.** Histadrut workers' housing; cornerstone June
1950, finished 1952, later absorbing immigrants from Iran and Georgia and then
Bukharan Jews in the 1960s–70s. ~8,830 residents (2012). Three sections; the
largest, "Shikun Vatikim", is two-storey buildings of four units on half-dunam
plots, criticised at the time for monotony and built of unplastered concrete
with damp problems; the eastern workers' units sit on the hillside with front
porches and red roofs. Holtz School (1954) on 30 dunams; Maccabi Tel Aviv
training facilities. Park HaHorshot opened along the western edge in 2013.
`diytlv` describes it as chilled, green and village-like, good for cyclists,
close to the Ayalon exit if you work south — and far from the centre, with buses
that do not run at weekends. (`wiki-he`, `diytlv`, `xnet-horshot`)

**grove_park — פארק החורשות.** Not an old neighborhood: a **new district** on
the north-west edge of Kiryat Shalom, also marketed as "קריית שלום צפון-מערב",
built on private land on the boundary between dense Tel Aviv and the open
southern landscape. 600+ housing units planned with new paths, community
services and centres; the first project is "Flora" (Carasso Nadlan, Shitrit,
VENN), aimed at young families. Named for Park HaHorshot to its west — the green
lung of south Tel Aviv, with playgrounds, a botanical garden, a historic well
house and areas left wild. A Green Line light-rail station is planned adjacent.
(`walla-nadlan`, `xnet-horshot`, `wiki-he`)

**neve_ofer — נווה עופר (תל כביר).** Built on the ruins of Abu Kabir, an Arab
quarter founded in the 1840s by Egyptian migrants and mostly demolished after
1948. Immigrant transit camp 1949–1963, resettled from the late 1960s with North
African and Bulgarian immigrants as "Tel Kabir", renamed in 1983 after housing
minister Avraham Ofer. Rehabilitated in the 1970s–80s and again in the 2000s,
which brought young families. The hard number: average units are under 60 m²
with about 20 m² per person — roughly **40% below the city average**. Two primary
schools, vocational training, a community centre. Borders Kiryat Shalom, Tel
Giborim in Holon, and Jaffa. (`wiki-he`)

**florentin — פלורנטין.** Founded 1927 by David Abarbanel and the contractor
Shlomo Florentin from Thessaloniki, planned as bourgeois mixed use with 3–4
storey buildings and narrow streets; part of Jaffa until 1948. 353 dunams, ~7,620
residents (2012). Original residents left from the late 1960s as small commerce
and light industry took over; municipal renewal from 1991 set off speculation and
a long fight with key-money tenants. Now the street-art capital of the city
(Dede and others), with Levinsky market, the 1938 Bauhaus HaAliya market building
and the Etzel museum. Consensus is remarkably consistent and mixed: the upside is
nightlife, cafés, cheap-for-central rent, a real young community and Levinsky and
Neve Tzedek within walking distance; the downside, said bluntly by `diytlv`, is
dirt and neglect, market noise by day and drunks and shop alarms at night, common
theft from ground-floor flats, damp and leaking old buildings, and loud
neighbours in tightly packed blocks. `makler-bestworst` files it as
"controversial" and explicitly bad for families. `nativeisrael` puts a 2-bed at
≈₪8,500 — above this budget. (`wiki-he`, `diytlv`, `makler-bestworst`,
`ronkin-2026`, `nativeisrael`, `alayof-2026`)

**kerem_hateimanim — כרם התימנים.** Founded 1906 on land of Aharon Shlush,
Yosef Bey Moyal and Haim Amzalag; named officially in 1929. Low-rise with
internal courtyards, adjoining houses and narrow alleys; the earliest homes used
wood and tin because residents had no money. Became the cradle of Israeli
Mizrahi popular music (Tzlilei HaKerem, Daklon, Chofni Cohen) via its restaurants
and chaflas. 4,720 residents on 374 dunams (2012). Heavily gentrified since the
1990s. `diytlv` is precise about the trade-off: minutes from the beach with the
Carmel market at the door and some streets with sea views, and the best parking
permit in the city precisely because there is no parking — against theft from
small buildings, noise, dirt and summer smells near the market, possible rats,
and damp/leak/wiring problems in old buildings with no lift. (`wiki-he`,
`diytlv`, `ronkin-2026`)

**neve_tzedek — נווה צדק.** Founded 1887, 22 years before Tel Aviv, the first
Jewish neighborhood outside Jaffa's walls, built by the Rokach and Shlush
families. 913 dunams, 3,870 residents (2012). Home to Agnon and Nahum Gutman;
slid into slum by the 1960s, restored from the 1980s by artists and
professionals. Shabazi Street is now galleries, cafés and design boutiques.
Consensus: the highest price per m² in the city, protected from new supply by
preservation rules; peaceful and beautiful — and expensive, tourist-trafficked,
hard for cars, with burglary risk in the low houses, maintenance problems behind
the gentrified prices, and few flats with a mamad because of preservation.
(`wiki-he`, `diytlv`, `ronkin-2026`, `makler-bestworst`)

**givat_herzl — גבעת הרצל.** Established 1948 as a working-class area on land
bought in the 1920s, absorbing two Arab neighborhoods of Abu Kabir; five
residents were killed by Egyptian air raids in May 1948. Today **primarily an
industrial and commercial district** — that is the operative fact for a renter.
Borders Florentin to the north, Neve Ofer to the south, Shapira to the east,
Jaffa to the west. Population density only 1.4 per dunam. 2012 figures: 61.8%
male, 71.6% Jewish, 69.7% arrived since 1990, 15.4% with a bachelor's degree and
18.6% without matriculation. Hurshat Park and a small zoo; a nature and
environment school and a democratic school. (`wiki-he`)

**tzahalon — צהלון ושיכוני חסכון.** Mixed Jewish-Arab Jaffa neighborhood west of
Jerusalem Blvd, named after the hospital in its north-east corner (opened 1933 by
the Arab physician Fuad Ismail Dagani, designed by Yitzhak Rapoport in the
International Style; reopened as Tzahalon after 1948, geriatric centre since
1980). Built in the 1950s over Ben-Gurion's objection — he wanted towers.
Low houses with gardens; still mostly Jewish but with a growing Arab
population; two Yemenite and one Sephardi synagogue. **No bus route runs through
it** because of the street layout — buses stop on the surrounding streets only.
(`wiki-he`)

**ajami_and_givat_aliyah — עג'מי וגבעת עליה.** Ajami was founded in the
mid-19th century by wealthy Maronite Arabs building in kurkar stone perpendicular
to the shore; poorer arrivals built more simply in the early 20th century. After
1948 it declined badly into crime and poverty; demolition plans in the 1950s
never became reconstruction, and from the 1970s every evacuated house was
destroyed, until the 1980s when the municipality recognised the area's historical
and architectural value and switched to preservation. Mixed Arab-Jewish, with
Maronite, Orthodox and Catholic churches and monasteries alongside a Muslim
population. Now trendy and attracting affluent residents, with empty plots still
scattered through it. Givat Aliyah is the quiet beachfront stretch south of it
that guides call a hidden gem — sea views, local atmosphere, off the tourist map.
Jaffa generally: cheaper the further south you go, superb food, beautiful old
buildings with high ceilings — against higher burglary rates, the central mosque's
amplified call to prayer, light-rail works on Jerusalem Blvd, and stadium noise
and football crowds. (`wiki-he`, `diytlv`, `nativeisrael`, `alayof-2026`)

**bavli — בבלי.** On the land of the Arab village Jamasin al-Gharbi; building
started 1957 as popular housing, with no bus service at first and a sewage
dispute that ended in a 1959 lawsuit over Yarkon pollution. Construction
companies moved in from the mid-1960s, producing four-storey "רכבת" blocks and
then 8–15 storey buildings and several towers. 9,403 residents on 1,294 dunams
(2015). Streets named after Talmudic figures; Tel Hashash, a 21-metre mound in
the middle, holds Hellenistic tombs and pottery from the Roman to early Islamic
periods. Became a middle-to-upper-class area. Consensus: peaceful, green, tucked
away, good schools, good transport, parks, "feels like a small town" — and
priced accordingly, well above this budget. (`wiki-he`, `nativeisrael`,
`ronkin-2026`)

**old_north_north / old_north_south — הצפון הישן.** District 3, Yarkon to
Bograsov/Ben-Zion/Marmorek, Ibn Gvirol to the sea. Built in the 1930s–40s on the
Geddes garden-city plan; part of the UNESCO White City. Originally settled by
affluent Central European immigrants of the Fourth and Fifth Aliyah, which is
where the word "צפוני" as shorthand for wealthy comes from. Dizengoff, Ben
Yehuda and Ibn Gvirol lengthwise; Nordau, Jabotinsky, Arlozorov, Ben Gurion and
Fishman across. Consensus: quiet, tree-lined, family-oriented, upmarket but not
polished, good schools and kindergartens, Yarkon Park and the old port nearby —
against high prices for little space, variable building quality, distance from
the real nightlife, light-rail works disrupting Ibn Gvirol and Arlozorov, and
parking that becomes impossible after 8pm. 2-bed ≈₪9,800. (`wiki-he`, `diytlv`,
`nativeisrael`, `ronkin-2026`)

**new_north_north / new_north_south / new_north_kikar_hamedina — הצפון החדש.**
District 4; Ben Gurion Ave to the Ayalon, Yarkon to Sha'ul HaMelech. ~42,700
residents (2008), 11.1% of the city. Built out 1948–1980s over farmland and Arab
villages; mostly 4–5 storey buildings on plots about 50% larger than the old
north, with 30-storey-plus towers arriving from the 1980s (the David Towers in
the 1970s were first). Kikar HaMedina is the commercial and luxury-retail hub;
Ichilov, the Tel Aviv Museum, the central station and Terminal 2000 are all in
the district. The preferred ground for developers since 2009 — high values plus
available land — which means constant TAMA 38 work. (`wiki-he`, `ronkin-2026`)

**ramat_aviv — רמת אביב.** North of the Yarkon, on the land of Sheikh Muwannis.
Founded in the 1950s around the Ramat Aviv Hotel — the neighborhood grew out of
the hotel rather than the reverse. Four parts: Ramat Aviv A (1950s, low-rise and
ground-level houses, ~10,170 residents), Ramat Aviv B / Neve Avivim (1960s–70s,
four boulevards around generous public space), Ramat Aviv C (1970s–90s, 12,000+
residents on ~1,100 dunams), and Ramat Aviv HaHadasha (1996–2016, apartment
buildings and malls). Tel Aviv University, the Eretz Israel Museum, the Palmach
Museum and the Rabin Center are here; Golda Meir lived in Ramat Aviv A. Consensus:
very quiet, very green, very safe, the best schools — and the most expensive rents
in the city (2-bed ₪11,000+), plus you need a car. (`wiki-he`,
`makler-bestworst`, `nativeisrael`)

**lamed — שכונת למד / תוכנית ל'.** North-west Tel Aviv, built in the 1970s;
renamed from "שיכון ל'" to "שכונת ל'" by mayor Roni Milo in 1998. The old part
is six- to eight-storey residential blocks. In 2015 the new part south of
Einstein St and west of Levi Eshkol — built on "הגוש הגדול" and called "למד
החדשה" — was joined to the neighborhood. Described as quiet and well-liked, with
a mixed population of families, long-time residents and professionals.
(`wiki-he`, `project-tlv`)

**lev_tel_aviv — לב תל אביב / לב העיר.** Rothschild, Sheinkin, Dizengoff,
Nachalat Binyamin, Habima; Bauhaus next to modern and eclectic and glass.
Consensus: central to everything, upmarket bars and cafés, good shopping, good
public transport, safe because it is never empty, relatively quiet side streets —
against high prices, essentially no parking without a private space, neighbour
and construction noise, and old badly-maintained buildings behind expensive
rents. `diytlv` gives studios at ₪4,000–5,000+ and 3-room at ₪8,000+, so a
2-room inside this budget here would be unusual. (`diytlv`, `makler-bestworst`,
`ronkin-2026`, `nativeisrael`)

**tel_aviv_port — נמל תל אביב.** The old port, now a boardwalk of restaurants,
shops and nightlife at the north-west end of the old north. Effectively an
entertainment district rather than a residential one. (`wiki-he`, `diytlv`)
