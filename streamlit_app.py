import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="SASHIGANE データ蓄積システム", page_icon="📊", layout="wide")

db.init_db()

st.title("📊 SASHIGANE データ蓄積システム")
st.caption(
    "GLMM用テストデータのExcelファイル（「テスト名」行、日本語ラベル行、英語キー行の順で始まり、"
    "その後にデータが続く形式）をアップロードすると、SQLiteデータベースに蓄積されます。"
)

uploaded_files = st.file_uploader(
    "Excelファイルをアップロード（複数選択可）",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
)

if uploaded_files:
    for uploaded_file in uploaded_files:
        file_bytes = uploaded_file.getvalue()
        file_hash = db.compute_file_hash(file_bytes)
        existing_name = db.file_already_uploaded(file_hash)

        with st.expander(f"📄 {uploaded_file.name}", expanded=True):
            if existing_name:
                st.warning(f"このファイルは既にアップロード済みです（{existing_name}）。スキップしました。")
                continue

            try:
                df = db.parse_excel(file_bytes)
            except ValueError as e:
                st.error(f"読み込みエラー: {e}")
                continue

            if df.empty:
                st.info("データ行がありませんでした。")
                continue

            inserted, duplicates = db.insert_records(df, uploaded_file.name)
            db.record_upload(uploaded_file.name, file_hash, len(df), inserted, duplicates)

            st.success(f"取り込み完了: {inserted} 件を追加しました。")
            if duplicates:
                st.warning(f"{duplicates} 件は既存データ（学習者ID・テスト項目・回数が同一）と重複していたためスキップしました。")

st.divider()

st.subheader("蓄積データ")
records = db.fetch_all_records()
st.metric("総レコード数", len(records))

if not records.empty:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        test_names = st.multiselect("テスト名で絞り込み", sorted(records["test_name"].dropna().unique()))
    with col2:
        learners = st.multiselect("学習者IDで絞り込み", sorted(records["learner_id"].dropna().unique()))
    with col3:
        items = st.multiselect("テスト項目で絞り込み", sorted(records["item"].dropna().unique()))
    with col4:
        groups = st.multiselect("組織名で絞り込み", sorted(records["group_name"].dropna().unique()))

    filtered = records
    if test_names:
        filtered = filtered[filtered["test_name"].isin(test_names)]
    if learners:
        filtered = filtered[filtered["learner_id"].isin(learners)]
    if items:
        filtered = filtered[filtered["item"].isin(items)]
    if groups:
        filtered = filtered[filtered["group_name"].isin(groups)]

    st.dataframe(filtered, use_container_width=True, hide_index=True)

    st.download_button(
        "蓄積データをCSVでダウンロード",
        data=filtered.to_csv(index=False).encode("utf-8-sig"),
        file_name="sashigane_accumulated_data.csv",
        mime="text/csv",
    )
else:
    st.info("まだデータが蓄積されていません。")

st.divider()

st.subheader("地域比較データ出力")
st.caption(
    "選んだ値を「対象」、それ以外を「その他」として分類したデータを出力できます"
    "（例: 都道府県で「東京」を選ぶと、東京 vs その他都府県で比較できます）。"
)

if not records.empty:
    compare_col1, compare_col2 = st.columns(2)
    with compare_col1:
        compare_field = st.selectbox(
            "比較する項目",
            ["pref", "region"],
            format_func=lambda x: {"pref": "都道府県", "region": "地域VS"}[x],
        )
    with compare_col2:
        compare_options = sorted(records[compare_field].dropna().unique())
        target_value = st.selectbox("対象にする値", compare_options) if compare_options else None

    if target_value is not None:
        comparison_df = records.copy()
        comparison_df["比較グループ"] = comparison_df[compare_field].apply(
            lambda v: target_value if v == target_value else "その他"
        )

        comparison_summary = (
            comparison_df.groupby("比較グループ")
            .agg(総レコード数=("id", "count"), 学習者数=("learner_id", pd.Series.nunique))
            .reset_index()
        )
        st.dataframe(comparison_summary, use_container_width=True, hide_index=True)

        st.download_button(
            f"「{target_value} vs その他」で分類したデータをCSVでダウンロード",
            data=comparison_df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"sashigane_comparison_{target_value}_vs_other.csv",
            mime="text/csv",
        )
else:
    st.info("まだデータが蓄積されていません。")

st.divider()

st.subheader("GLMM分析可能性チェック")
st.caption("テスト名・テスト項目ごとに、GLMM分析に必要なデータ量が揃っているかを確認できます。")

if not records.empty:
    threshold_col1, threshold_col2 = st.columns(2)
    with threshold_col1:
        min_learners = st.number_input(
            "最低学習者数（ランダム効果のグループ数）", min_value=1, value=10, step=1
        )
    with threshold_col2:
        min_records = st.number_input("最低総レコード数", min_value=1, value=30, step=1)

    readiness = (
        records.groupby(["test_name", "item"], dropna=False)
        .agg(総レコード数=("id", "count"), 学習者数=("learner_id", pd.Series.nunique))
        .reset_index()
        .rename(columns={"test_name": "テスト名", "item": "テスト項目"})
        .sort_values(["テスト名", "テスト項目"])
    )
    readiness["分析可能"] = (
        (readiness["学習者数"] >= min_learners) & (readiness["総レコード数"] >= min_records)
    ).map({True: "✅ 分析可能", False: "❌ データ不足"})

    st.dataframe(readiness, use_container_width=True, hide_index=True)
else:
    st.info("まだデータが蓄積されていません。")

st.divider()

st.subheader("アップロード履歴")
history = db.fetch_upload_history()
if not history.empty:
    st.dataframe(history, use_container_width=True, hide_index=True)
else:
    st.info("アップロード履歴はありません。")
