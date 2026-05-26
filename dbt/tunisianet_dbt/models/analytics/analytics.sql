-- models/analytics/analytics.sql
{{
    config(materialized='table')
}}

with base as (
    select
        p.id         as product_id,
        p.brand,
        pr.price,
        pr.discount,
        r.rank
    from {{ ref('product') }}  p
    join {{ ref('price') }}    pr on pr.product_id = p.id
    join {{ ref('ranking') }}  r  on r.product_id  = p.id
),

-- Compute the top 50% rank threshold dynamically from actual rank values
rank_bounds as (
    select
        max(rank)                    as total_ranked,
        max(rank) / 2.0              as top_half_threshold
    from {{ ref('ranking') }}
),

filtered as (
    select
        b.product_id,
        b.brand,
        b.price,
        b.discount,
        b.rank
    from base b
    cross join rank_bounds rb
    where
        b.discount is null                  -- keep only  products without discount
        and b.rank <= rb.top_half_threshold     -- top 50% (e.g. rank <= 50 if max is 100)
),

aggregated as (
    select
        brand,
        round(avg(price)::numeric, 2)           as average_price,
        percentile_cont(0.5) within group (
            order by rank
        )::numeric                              as median_rank
    from filtered
    group by brand
    having avg(price) > 300
)

select
    brand,
    average_price,
    median_rank
from aggregated
order by average_price desc