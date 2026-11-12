-- 02_stg_users.sql
-- STAGING for the user registry: the cleaned version of users.csv.
-- Input : raw_users (users.csv exactly as delivered)
-- Output: stg_users  one row per row of users.csv (user_id is unique there: check U9 = 0 duplicates)
--
-- Cleaning rules (issue codes refer to reports/01_data_quality.md):
--   age            outside 4-92 -> NULL (U1-U4, U11). age_raw keeps the delivered value. No imputation.
--   age_band       5 bands, plus 'Unknown' for NULL age
--   gender         missing -> 'unknown', its own segment (U5). No imputation.
--   acquisition_channel  missing -> 'Unknown'
--   registered_date      YYYYMMDD integer -> DATE
--   flag_registered_after_data_end  registration after 2017-03-31 (U7): kept and flagged
-- Rules that need the transactions (registration after the first payment, U8; tenure start) are
-- applied in dim_user, where users and transactions meet.
-- churn_labels.csv needs no staging: no duplicate users (L1 = 0) and no invalid values (L2 = 0),
-- so raw_churn_labels is used as delivered.

CREATE OR REPLACE TABLE stg_users AS
SELECT
  user_id,
  city,
  coalesce(acquisition_channel::VARCHAR, 'Unknown')             AS acquisition_channel,
  age                                                           AS age_raw,
  CASE WHEN age BETWEEN 4 AND 92 THEN age END                   AS age,
  CASE WHEN age BETWEEN 4 AND 17  THEN '4-17'
       WHEN age BETWEEN 18 AND 24 THEN '18-24'
       WHEN age BETWEEN 25 AND 34 THEN '25-34'
       WHEN age BETWEEN 35 AND 44 THEN '35-44'
       WHEN age BETWEEN 45 AND 92 THEN '45-92'
       ELSE 'Unknown' END                                       AS age_band,
  coalesce(gender, 'unknown')                                   AS gender,
  strptime(registered_at::VARCHAR, '%Y%m%d')::DATE              AS registered_date,
  (registered_at > 20170331)::TINYINT                           AS flag_registered_after_data_end
FROM raw_users;

-- Validation: one row per raw row, user_id unique, no age outside 4-92.
SELECT
  (SELECT count(*) FROM raw_users)                              AS raw_rows,
  count(*)                                                      AS stg_rows,
  count(*) - count(DISTINCT user_id)                            AS dup_user_id,
  count(*) FILTER (WHERE age IS NULL)                           AS age_unknown,
  count(*) FILTER (WHERE gender = 'unknown')                    AS gender_unknown,
  count(*) FILTER (WHERE age NOT BETWEEN 4 AND 92)              AS age_out_of_range
FROM stg_users;
