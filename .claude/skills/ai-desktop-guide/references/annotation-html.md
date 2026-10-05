# 注釈 HTML の書き方

`show_annotated` の `html` は、撮影画像と同じ大きさ（`imageWidth × imageHeight` ピクセル）の層に重ねられる。すべて `position: absolute` で、`style` の `left` / `top` などを画像のピクセルで書く。ページ全体は表示幅に合わせて拡大縮小されるので、位置はずれない。

## 部品

```html
<!-- 枠: 対象を囲む。left/top/width/height -->
<div class="box" style="left:120px;top:80px;width:220px;height:40px"></div>

<!-- 番号: left/top は丸の中心。枠の左上の角に置くと読みやすい -->
<div class="badge" style="left:120px;top:80px">1</div>

<!-- 吹き出し: left/top は左上。最大幅 320px。対象の右か下の空いた場所に -->
<div class="note" style="left:360px;top:70px">ここをクリックして「設定」を開きます</div>

<!-- 矢印: layer は画像全体を覆う SVG。座標は画像のピクセル -->
<svg class="layer"><line class="arrow" x1="360" y1="90" x2="345" y2="100"/></svg>
```

## 手順の例（3 ステップ）

```html
<div class="box" style="left:40px;top:12px;width:60px;height:28px"></div>
<div class="badge" style="left:40px;top:12px">1</div>
<div class="box" style="left:300px;top:200px;width:180px;height:32px"></div>
<div class="badge" style="left:300px;top:200px">2</div>
<div class="box" style="left:620px;top:520px;width:90px;height:30px"></div>
<div class="badge" style="left:620px;top:520px">3</div>
<div class="note" style="left:500px;top:40px">① ファイル → ② 名前を付けて保存 → ③ 保存</div>
```

## コツ

- 座標は撮影画像を見て決める。迷うときは対象より少し大きめに囲む（数ピクセルのずれは許容される）。
- 吹き出しは対象の上に重ねない。画面端（右 320px 以内など）にはみ出す位置なら、左側や下側に置く。
- 矢印は吹き出しから対象へ向ける（`x2/y2` が矢じり側）。長い矢印より、近くに置いた吹き出しの方が読みやすい。
- 1 ページの注釈は 5 個程度まで。多いときはボタンで次のページに分ける。
- 長い説明は `html` ではなく `explanation`（画像の下に表示される）に書く。
