SELECT sr."Ngày ghi"::date, sum(sr."Doanh thu thực hiện" ) FROM public.sales_revenue AS sr
group by 1
order by 1 desc