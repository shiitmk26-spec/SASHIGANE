import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="SASHIGANE データ蓄積システム", page_icon="📊", layout="wide")

db.init_db()

st.title("📊 SASHIGANE データ蓄積システム")
st.caption(
    "GLMM用テストデータのExcelファイル（1行目: 日本語ラベル、2行目: 英語キー、3行目以降: データ）を"
    "アップロードすると、SQLiteデータベースに蓄積されます。"
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
    col1, col2, col3 = st.columns(3)
    with col1:
        learners = st.multiselect("学習者IDで絞り込み", sorted(records["learner_id"].dropna().unique()))
    with col2:
        items = st.multiselect("テスト項目で絞り込み", sorted(records["item"].dropna().unique()))
    with col3:
        groups = st.multiselect("組織名で絞り込み", sorted(records["group_name"].dropna().unique()))

    filtered = records
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

st.subheader("GLMM分析可能性チェック")
st.caption("テスト項目ごとに、GLMM分析に必要なデータ量が揃っているかを確認できます。")

if not records.empty:
    threshold_col1, threshold_col2 = st.columns(2)
    with threshold_col1:
        min_learners = st.number_input(
            "最低学習者数（ランダム効果のグループ数）", min_value=1, value=10, step=1
        )
    with threshold_col2:
        min_records = st.number_input("最低総レコード数", min_value=1, value=30, step=1)

    readiness = (
        records.groupby("item")
        .agg(総レコード数=("id", "count"), 学習者数=("learner_id", pd.Series.nunique))
        .reset_index()
        .rename(columns={"item": "テスト項目"})
        .sort_values("テスト項目")
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
