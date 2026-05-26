{{
    config(
        materialized='incremental',
        unique_key='id',
        incremental_strategy='merge',
        merge_update_columns=['name', 'brand', 'image_url', 'product_url', 'updated']
    )
}}

with source as (
    select * from {{ ref('stg_raw_data') }}
)

select
    id,
    name,
    brand,
    image_url,
    product_url,
    -- created: first time we saw this product
    {% if is_incremental() %}
        coalesce(
            (select created from {{ this }} where id = source.id),
            scraped_at
        ) as created,
    {% else %}
        scraped_at as created,
    {% endif %}
    scraped_at as updated
from source