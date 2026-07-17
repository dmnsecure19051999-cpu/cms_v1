CREATE OR REPLACE VIEW "Update_Customer_Info"."Firstdayofcustomer" AS
 WITH latest_customer AS (
         SELECT cd.id,
            cd.ten_khach_hang,
            row_number() OVER (PARTITION BY cd.id ORDER BY cd.ngay_cuoi_cap_nhat DESC) AS rn
           FROM customer_data cd
        ), bill_days AS (
         SELECT DISTINCT lc.id,
            lc.ten_khach_hang,
            (sr.ngay_ghi)::date AS "NgayHD"
           FROM ((sales_revenue sr
             LEFT JOIN latest_customer lc ON (((sr.id_khach_hang = lc.id) AND (lc.rn = 1))))
             LEFT JOIN cancellation_bills cb ON ((sr.ma_hoa_don = cb.ma_hoa_don)))
          WHERE (cb.ma_hoa_don IS NULL)
        )
 SELECT id,
    ten_khach_hang,
    min("NgayHD") AS "Ngay_dau_tien"
   FROM bill_days bd
  GROUP BY id, ten_khach_hang;