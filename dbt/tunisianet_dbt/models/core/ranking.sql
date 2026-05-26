{{
    config(
        materialized='incremental',
        unique_key='product_id',
        incremental_strategy='merge',
        merge_update_columns=['rank', 'max_rank', 'updated']
    )
}}

with source as (
    select * from {{ ref('stg_raw_data') }}
),

-- Compute the historical max rank per product across ALL raw_data rows
all_ranks as (
    select
        id         as product_id,
        max(rank)  as max_rank
    from {{ source('public', 'raw_data') }}
    group by id
),

combined as (
    select
        s.id        as product_id,
        s.rank,
        a.max_rank,
        s.scraped_at
    from source s
    join all_ranks a on a.product_id = s.id
)

select
    -- Auto-generate surrogate key
    {{ dbt_utils.generate_surrogate_key(['product_id']) }} as id,
    product_id,
    rank,
    max_rank,
    {% if is_incremental() %}
        coalesce(
            (select created from {{ this }} where product_id = combined.product_id),
            scraped_at
        ) as created,
    {% else %}
        scraped_at as created,
    {% endif %}
    scraped_at as updated
from combined