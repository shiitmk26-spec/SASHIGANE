# 📊 SASHIGANE データ蓄積システム

GLMM（一般化線形混合モデル）用テストデータのExcelファイルをアップロードすると、
内容をSQLiteデータベースへ蓄積していくStreamlitアプリです。

## 対応するExcelの形式

- 1行目: 日本語ラベル（表示用）
- 2行目: 英語キー（`learner_id`, `region`, `pref`, `year`, `group_name`, `video`, `practice`, `trial`, `item`, `score`, `max_score`）
- 3行目以降: データ

## 重複の扱い

- 同一ファイル（内容ハッシュが一致）を再アップロードした場合は、ファイル全体をスキップします。
- ファイル内の各行は `学習者ID + テスト項目 + 回数` の組み合わせで重複を判定し、既存データと重複する行はスキップします。

## ローカルでの実行方法

1. Install the requirements

   ```
   $ pip install -r requirements.txt
   ```

2. Run the app

   ```
   $ streamlit run streamlit_app.py
   ```

蓄積データは `data/sashigane.db`（SQLite）に保存されます。
