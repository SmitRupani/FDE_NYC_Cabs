# Known / Unknown / Assumption / Limitation (KUAL) Framework

**Project Track:** Track B — NYC Taxi & Limousine Commission (TLC)  
**Author:** Forward Deployed Engineer (FDE)  
**Target Ingestion Period:** January 2026 (`yellow_tripdata_2026-01.parquet`)  

---

## 1. Executive Summary

A core principle of Forward Deployed Engineering is that **data pipelines should never make silent, undocumented transformations.** When moving from messy real-world client data to a business decision, every choice must be explicit, defensible, and audited.

This document formally records the **Knowns**, **Unknowns**, **Assumptions**, and **Limitations** underlying the NYC TLC Data Foundations Pipeline.

---

## 2. The Four Pillars of Analytical Governance

### A. Known Facts (Empirically Verified in Pipeline)
1. **Source Dataset Scale:** The January 2026 raw yellow taxi parquet contains exactly **3,724,889 trip records** across 20 attributes, with a SHA-256 hash of `8b3933fe6f0d7b6d8826613c0dd724edc680ff7c49e2bd4c7635c05102728637`.
2. **Spatial Polygon Coverage:** The official TLC taxi zone lookup maps **263 valid spatial zones** across the 5 boroughs of New York City, plus Newark Airport (EWR, Zone 1). Zones 264 (NV / Unknown) and 265 (NA) represent unmapped rides.
3. **Data Quality Pass Rate:** Following the application of 10 business validation rules, **3,463,451 trips (92.98%)** met all operational quality standards and were promoted to the curated fact table. Exactly **261,438 records (7.02%)** failed one or more criteria and were safely isolated in the quarantine repository with diagnostic tags.
4. **Gross Financial Volume:** Total validated passenger expenditures in January 2026 reached **$101,279,200.00**, generating **$5,575,460.00** in MTA congestion surcharges and **$372,296.75** in airport access fees.
5. **Electronic Tip Reporting:** In electronic credit card transactions (`payment_type = 1`), digital tips average **19.8% of the fare amount**.

---

### B. Unknown Variables (Unobserved in Source Systems)
1. **Cruising & Deadheading Distance:** The TPEP feed records metrics only between meter drop and meter stop. The duration and distance a driver spends cruising empty, staging at taxi queues, or driving home at the end of a shift are completely unobserved.
2. **Cash Gratuities:** Taximeters do not require drivers to enter cash tips. Consequently, recorded tip amounts for cash transactions (`payment_type = 2`) are $0.00 in 99.99% of records. Real-world driver cash tip earnings are unobserved.
3. **Hailing Mechanism (Street Hail vs Digital E-Hail):** Standard yellow cabs accept both traditional hand waves from the street and digital dispatch via licensed apps (e.g., Curb, Arro). The source feed does not distinguish between these hailing mechanisms.
4. **Turn-by-Turn Routing & Exact Path:** Due to privacy regulations enacted in 2016, GPS coordinates were aggregated to zone centroids. We cannot observe whether a driver took the FDR Drive, Broadway, or 8th Avenue, nor can we detect precise mid-trip traffic slowdown points.
5. **Passenger Rejections & Unfulfilled Demand:** Unmet demand—such as passengers who attempted to hail a taxi but were passed by, or passengers who abandoned a hail due to long waits—is completely absent from the dataset.

---

### C. FDE Assumptions & Engineering Judgement Calls

#### Judgement Call 1: The 29.2% Null Passenger Count / RateCode Anomaly
- **The Empirical Finding:** Exactly **1,088,058 records (29.21%)** in the raw dataset have `NULL` values for `passenger_count`, `RatecodeID`, `store_and_fwd_flag`, `congestion_surcharge`, and `Airport_fee`. All of these records coincide with `payment_type = 0` (unspecified dispatch).
- **The Pitfall:** A naive pipeline would run `df.dropna()` or filter `WHERE passenger_count > 0`, silently dropping **1.09 million legitimate rides** and understating monthly citywide taxi volume by nearly 30% ($31 million in gross spend).
- **The FDE Judgement:** We retain these records in `fct_trips` for all operational volume, congestion speed, and revenue calculations. For `RatecodeID`, we coalesce null values to `99 (Unassigned / Digital Dispatch)`. Null `passenger_count` values are preserved as nulls, excluding them only when calculating passenger occupancy metrics.

#### Judgement Call 2: The 60-Second Trip Duration Floor
- **The Finding:** 83,747 trips have a duration of under 60 seconds, of which 45,069 have an exact duration of 0 seconds.
- **The FDE Judgement:** Physical urban passenger trips cannot be completed in under 60 seconds. These records represent false starts (passenger enters, driver drops meter, passenger immediately cancels or driver refuses the destination). Rather than silently keeping or dropping them, we route them to the quarantine table with code `DURATION_UNDER_1MIN` to allow fleet operators to audit driver meter usage and cancellation patterns.

#### Judgement Call 3: The 85-mph Speed Ceiling
- **The Finding:** 447 trips exhibit calculated effective speeds exceeding 85 mph, with extreme outliers reaching thousands of miles per hour (e.g., trip distance = 269,097 miles in 15 minutes).
- **The FDE Judgement:** Given NYC speed limits (25 mph citywide, 50 mph on limited-access parkways), sustained speeds over 85 mph are physically impossible in a yellow taxi. These represent odometer pulse errors, GPS coordinate jumps, or meter reset glitches. They are tagged `SPEED_OVER_85MPH` and quarantined to prevent skewing congestion metrics.

#### Judgement Call 4: Negative Fares as Auditable Quarantine
- **The Finding:** 40,435 records have negative fares or negative total amounts (e.g., `-$15.00`), representing refunds, credit card chargebacks, or manual meter correction adjustments.
- **The FDE Judgement:** Negative amounts should not be subtracted directly from forward trip volume (since they distort trip duration and velocity averages). Instead, they are routed to `quarantined_trips` with the flag `NON_POSITIVE_FARE` so financial auditors can reconcile dispute rates without corrupting operational transit models.

---

### D. Pipeline Limitations & Future Scope
1. **Zone-Centroid Speed Approximation:** Speed calculations rely on taximeter odometer distance divided by duration, rather than turn-by-turn routing telemetry. While highly accurate for overall transit velocity, speeds can be artificially deflated if a driver takes a circuitous route or waits at a drive-thru.
2. **Monthly Batch Grain:** The pipeline operates on completed monthly batches. Real-time fleet management would require transitioning this architecture to a streaming pipeline (e.g., Apache Kafka / Flink or DuckDB streaming ingestion).
3. **Refund Reconciliation Matching:** In the current version, quarantined negative refunds are isolated but not joined back to their original forward trip IDs. Future iterations could incorporate fuzzy matching on vehicle medallion and pickup timestamp to net out disputed fares.
