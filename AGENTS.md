# AGENTS.md

## プロジェクトの目的

このリポジトリでは、研究資料を対象としたローカルRAGアプリを開発する。

## 現在のマイルストーン

現在は、macOSデスクトップ版v0.1.0のrelease readiness段階にある。初回ユーザー向けonboarding、release documentation、最終release準備を進める。

複数PDF対応のGUI／RAG、SQLite永続化schema v3、文書変更検出は実装済みである。`QStandardPaths.AppDataLocation`に使うapplication identityと保存先は互換性のため維持する。real tag、GitHub Release、Developer ID署名、notarization、publishは、明示的な許可なしに実行しない。生成した`.app`、DMG、iconset、PDF、DBなどのbuild／validation artifactはcommitしない。

## コーディング規則

- Pythonの型ヒントを付ける
- パスには可能な限り `pathlib.Path` を使う
- ページ番号は利用者向けの1始まりとする
- 1つのチャンクが複数ページをまたがないようにする
- 外部依存を追加するときは理由を説明する

## テスト規則

- テストには `pytest` を使う
- Ollamaへの接続は単体テストではモック化する
- 変更後に関連するテストを実行する
- テストが失敗している状態で完了と報告しない
