# ChatGPT ile oda fotoğrafları (60 oda)

Renk görselleri bir oda fotoğrafına asılır. Boş duvarlı odaları ChatGPT'ye çizdirip panele yükleyebilirsin
(panelde Odalar → AI ile oda üret de var; o, API bütçenden harcar).

Kullanım:
1. ChatGPT'de **yeni sohbet** aç, aşağıdaki **ana prompt**u yapıştır.
2. Her mesajda listeden **bir satırı olduğu gibi** yapıştır (ör. `15. Western ranch living room, ...`).
3. **Her ~10 odada bir yeni sohbet** aç ve ana prompt'u tekrar yapıştır (eski görsellere benzetmesin).
4. Görselleri indir, panel → **Odalar → Fotoğraf yükle** ile toplu yükle.

Iskarta kuralı: duvara tablo, saat, ayna, raf ya da lamba koymuşsa, eğik çekmişse, insan varsa ya da renkler
turuncu/aşırı doygunsa → "Duvar tamamen boş olsun, renkler doğal olsun, aynı sahneyi tekrar çiz" yaz.

## Ana prompt

```
I am building a library of empty-wall room photos to use as backgrounds for metal wall art mockups.
Each message I send describes ONE scene. Generate exactly ONE image of that scene, following ALL of these rules:

- Realistic photograph with natural, true-to-life colors: neutral white balance, NOT oversaturated,
  no orange or golden color cast, no glow, no HDR or illustration look.
- Follow the wall color, materials and style in my description exactly. Every scene must look clearly
  different from the previous ones: different furniture, different decor, different lighting
  (bright daylight, soft overcast or calm evening light), different arrangement of the lower part.
- Landscape 3:2. Camera straight-on to the main wall, at eye level, about 35mm lens. No tilt: vertical
  lines perfectly vertical, horizon level, no wide-angle distortion.
- The main wall has a LARGE, completely EMPTY, evenly lit area in the upper middle of the image
  (roughly from 25% to 75% of the width and from 8% to 50% of the height). Nothing on that wall:
  no art, frames, mirrors, clocks, shelves, lamps, sconces, plants, hooks, windows, TV or text,
  and no light spots or reflections on it.
- Furniture and decor only in the lower part of the image, below that empty wall area.
- Exterior scenes only when my description says "exterior".
- No people, no pets, no text, no logos, no brand-name products.

Reply with the image only.
```

## Oda listesi (her mesaja bir satır)

```
LIVING ROOM
1. Modern minimalist living room, warm white wall, light gray sofa, oak floor
2. Scandinavian living room, soft white wall, beige sofa, light oak floor, wool rug
3. Modern farmhouse living room, white shiplap wall, linen slipcovered sofa
4. Rustic cabin living room, natural pine plank wall, brown leather sofa
5. Mid-century modern living room, sage green wall, walnut sideboard, mustard armchair
6. Boho living room, terracotta limewash wall, cream sofa, rattan accents
7. Industrial loft living room, exposed red brick wall, cognac leather sofa
8. Dark moody living room, charcoal gray wall, deep green velvet sofa
9. Coastal living room, light sand beige wall, white sofa, jute rug
10. Japandi living room, warm greige wall, low wooden sofa, paper floor lamp on the floor
11. Living room with navy blue wall, cream sofa, brass side table
12. Living room with deep forest green wall, camel leather sofa
13. Living room with matte black wall, light gray sofa, light wood floor
14. Living room with smooth light concrete wall, modern gray sofa
15. Western ranch living room, warm cream plaster wall, leather sofa with wool throws
16. Mediterranean living room, white lime plaster wall, linen sofa, terracotta floor tiles
17. Traditional living room, pale blue-gray wall, tufted sofa
18. Living room with white board-and-batten wall, gray sectional sofa

BEDROOM
19. Bedroom, warm white wall, upholstered linen headboard, white bedding
20. Scandinavian bedroom, light gray wall, oak bed frame
21. Bedroom with navy blue wall, white bedding, wooden nightstands
22. Rustic cabin bedroom, wood plank wall, plaid blanket
23. Boho bedroom, cream wall, rattan headboard, layered textiles
24. Bedroom with sage green wall, natural linen bedding
25. Bedroom with charcoal wall, light gray bedding
26. Neutral kids' bedroom, soft white wall, simple wooden bed

ENTRYWAY / HALLWAY
27. Entryway, white wall, slim wooden console table
28. Farmhouse entryway, white shiplap wall, wooden bench with baskets
29. Entryway, greige wall, black metal console table
30. Hallway / staircase landing, plain white wall, wooden floor
31. Entryway with dark green wall, brass and wood console
32. Mudroom, white board-and-batten wall, built-in bench
33. Entryway with terracotta wall, rattan console table

DINING / KITCHEN
34. Dining room, warm white wall, wooden table and chairs
35. Dining room with black wall, oak table, cane chairs
36. Farmhouse dining room, shiplap wall, long rustic table
37. Dining room with sage green wall, round wooden table
38. Kitchen breakfast nook, white wall, small round table and two chairs
39. Kitchen dining nook, cream wall, built-in bench seat
40. Kitchen wall above a wooden bench, light gray wall
41. Dining room with navy wall, white chairs, wooden table

OFFICE / READING
42. Home office, white wall, wooden desk and chair
43. Home office with dark gray wall, walnut desk
44. Home office with olive green wall, oak desk
45. Reading nook, cream wall, leather armchair and side table
46. Industrial office, concrete wall, metal and wood desk
47. Game room / man cave, dark charcoal wall, leather club chairs

RUSTIC / SPECIAL
48. Log cabin interior, round log wall, stone floor
49. Mountain lodge, rough reclaimed barn wood wall
50. Covered farmhouse porch, white wood siding wall, rocking chairs (exterior)
51. Garage workshop, painted gray wall, wooden workbench (nothing hanging on the wall)
52. Southwestern ranch house, adobe-style warm plaster wall
53. Lake house, light blue-gray shiplap wall
54. Mountain chalet, dark stained wood wall

OUTDOOR (exterior)
55. Covered patio, white stucco exterior wall, outdoor lounge chairs (exterior)
56. Front porch next to the door, gray lap siding wall, potted plants on the floor (exterior)
57. Backyard, horizontal cedar fence panels, garden bed below (exterior)
58. Garden, red brick wall, plants at the base (exterior)
59. Front entrance, white painted brick wall, two planters on the ground (exterior)
60. Pergola patio, beige stucco wall, outdoor dining set (exterior)
```

## Notlar

- ChatGPT web görselleri ~1536×1024 çıkar; Etsy boyutunda (3000 px) arka plan hafif yumuşak görünür, ürün
  kodla çizildiği için keskin kalır (fotoğrafta odak üründeymiş gibi).
- Abonelikte görsel üretim sınırı var; 60 oda birkaç oturuma yayılabilir.
- 50-60 dış mekân odaları dış mekâna uygun ürünler (tabela, çit süsü) içindir.
- Yüklendikten sonra her odanın yerleşim kutusu varsayılan olarak üst-orta bölgededir (genişlik %25-75, yükseklik %5-51; ana
  prompt bu bölgeyi boş istediği için çoğu odada doğru düşer); sapan odada Odalar sayfasında sürükleyerek düzelt.
