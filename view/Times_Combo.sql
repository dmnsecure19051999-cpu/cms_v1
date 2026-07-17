CREATE OR REPLACE VIEW "Update_Bills"."Times_Combo" AS
 SELECT khach_hang,
    id_khach_hang,
    count(DISTINCT ma_hoa_don) AS so_lan_len_goi
   FROM "Update_Bills"."UpdateBill" u
   WHERE (((u.loai_du_lieu)::text = 'Thông tin thanh toán'::text)
      AND ((u.loai_doanh_thu)::text = 'Gói trị liệu'::text)
      AND ((u.ngay_ghi)::date >= DATE '2026-01-01')
      AND ((u.ngay_ghi)::date < DATE '2026-07-16')
      AND (((u.san_pham)::text ~~ '%Xoa bóp%'::text) OR ((u.san_pham)::text ~~ '%Hào châm%'::text)))
  GROUP BY khach_hang, id_khach_hang;