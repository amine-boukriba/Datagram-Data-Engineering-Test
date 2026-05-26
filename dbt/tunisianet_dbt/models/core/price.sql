{{
    config(
        materialized='incremental',
        unique_key='product_id',
        incremental_strategy='merge',
        merge_update_columns=['price', 'price_old', 'discount', 'updated']
    )
}}

with source as (
    select * from {{ ref('stg_raw_data') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['id']) }} as id,
    id          as product_id,
    price,
    old_price   as price_old,
    -- Discount: positive difference only, else null
    case
        when old_price is not null
         and old_price > price
        then round(old_price - price, 2)
        else null
    end          as discount,
    {% if is_incremental() %}
        coalesce(
            (select created from {{ this }} where product_id = source.id),
            scraped_at
        ) as created,
    {% else %}
        scraped_at as created,
    {% endif %}
    scraped_at  as updated
from source