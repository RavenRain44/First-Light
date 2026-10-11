The Wilmington catalog retains public original station sources for Florence (September 14, 2018), Dorian (September 6, 2019), Isaias (August 4, 2020), and a station normal-weather control (October 16, 2024).

`wilmington-originals.json` includes the source URLs, retrieval times, download SHA-256 digests, and independently checked digests of the retained source rows. It contains ILM METAR observations and issued KILM GFS MOS runs. Forecast wind is sustained wind in knots before conversion to mph; temperature is Fahrenheit and P06 is precipitation probability. GFS Q06 and SNW are categorical and are never interpreted as precipitation, snow, or ice accumulation amounts.

The selected report uses only METAR validity times at least 15 minutes before evaluation and GFS run timestamps at least two hours before evaluation. These availability lags are estimates: neither archive records exact original publication or ingestion times. Later observations remain independent outcome context and never enter the selected report's assessment or Akamai brief.

Original warning updates, storm-surge/flood forecast products, road access, cameras, evacuation orders, facility flood depth, and actual office decisions are not retained. This is a partial station reconstruction and cannot establish coastal safety or comprehensive hurricane forecast accuracy. The complete 24-hour station record verifies the normal control against a frozen local station disruption definition; it does not prove no coastal alerts or flooding existed elsewhere.

To explicitly retrieve the bounded public sources again, from `backend/` run:

```sh
python -m scripts.build_wilmington_history --online
```

This uses public HTTP archives and no paid inference. Committed fixtures support the curated catalog, timelines, and selected reports without network access. The dates and event identifiers are kept separate from the immutable Ames historical baselines.
