# MySQL SQL Dialect Rules

## Date Functions
- Use YEAR(), MONTH(), DAY(), QUARTER() to extract date parts
- Use DATE_FORMAT(date, '%Y-%m') to format dates
- Use CURDATE() for current date
- Use DATE_SUB(date, INTERVAL n MONTH) for date arithmetic
- Use BETWEEN '2024-06-01' AND '2024-06-30' for date range filtering

## String Functions
- Use LIKE '%keyword%' for fuzzy matching
- Use CONCAT() for string concatenation

## Aggregation
- SUM(), COUNT(), AVG(), MAX(), MIN() standard aggregation
- COUNT(DISTINCT column) for distinct count
- GROUP BY + ORDER BY for grouping and sorting

## Window Functions
- SUM(...) OVER() for totals
- ROW_NUMBER() OVER(ORDER BY ...) for ranking

## Notes
- Do NOT use Presto/Trino functions (date_trunc, approx_percentile, etc.)
- Use ROUND(..., 2) for monetary calculations
- Use explicit JOIN ... ON syntax
- Chinese strings use single quotes: '华东'
