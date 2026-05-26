-- Deduplicate: keep only the latest scraped row per product id
with deduped as (
    select
        id,
        name,
        price,
        old_price,
        brand,
        rank,
        image_url,
        product_url,
        scraped_at,
        row_number() over (
            partition by id
            order by scraped_at desc
        ) as rn
    from {{ source('public', 'raw_data') }}
)

select
    id,
    name,
    price,
    old_price,
    brand,
    rank,
    image_url,
    product_url,
    scraped_at
from deduped
where rn = 1