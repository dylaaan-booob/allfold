# UI sources and notices

These are the editable UI sources and local assets. The build copies delivery resources into Python's static tree. Sources and license files stay with their assets.

## Adapted code and artwork

| Source | Fixed revision | Use and notice |
| --- | --- | --- |
| RhinE | `aa92ac9aa8fd8c611f5121583ae7c2a406b52607`, `7ebb9dbbcc0dacf89fb9a8f49a6b523aefe063ce` | Archive sprites, inspection frames, layout and control adaptations. MIT, Copyright (c) 2026 the Audio Archive authors. [Notice](licenses/RhinE-MIT.txt) |
| Blog Theme | `6f1e5b0c9a7e9b253db8b8a9b93a397c07d7ba93` | Transitions, decryption, Discover video and retained Kept scene inputs. MIT, Copyright (c) 2026 LBEILC. [Notice](licenses/Blog-Theme-MIT.txt) |
| RhineLabUI | `12cc5e4013acb9408f753ff71de6b8492299b7c8` | Settings form and controls. MIT, Copyright (c) 2026 LBEILC. [Notice](licenses/RhineLabUI-MIT.txt) |
| [Justice](https://github.com/kitlangton/justice) | `@kitlangton/justice` 0.3.1, `0930a34b1fb0421e859cb66db4ce2ae9b6778f90` | Local `justice.js` engine. MIT, Copyright (c) 2026 Kit Langton. [Notice](licenses/Justice-MIT.txt) |
| [Cropper.js](https://github.com/fengyuanchen/cropperjs/tree/v1.7.0) | 1.7.0 | Unmodified JS/CSS in `assets/vendor/cropperjs-1.7.0/`. MIT, Chen Fengyuan. [Notice](licenses/Cropperjs-MIT.txt) |

Justice is a retained local asset, rebuilt from the fixed npm package's `dist/engine.js` with esbuild as an IIFE named `Justice`; normal UI setup does not redownload it. Version 0.3.1 supplies the MIT notice for the unchanged 0.3.0 engine. Cropper.js is loaded locally without a CDN.

## Fonts

| Font | Local asset and source | Notice |
| --- | --- | --- |
| Geist Mono | Bundled regular, medium and SemiBold font files | [SIL OFL](licenses/Geist-OFL.txt) |
| MiSans | Bundled font files | Original notice and license PDF in [licenses](licenses/) |
| Source Sans 3 | Unmodified variable upright WOFF2, [Adobe 3.052R](https://github.com/adobe-fonts/source-sans/tree/3.052R), `assets/fonts/SourceSans3VF-Upright.ttf.woff2` | SIL OFL 1.1, Copyright 2010-2022 Adobe, Reserved Font Name 'Source'. [Complete notice](licenses/Source-Sans-3-OFL.txt) |
| Novecento Sans Wide Bold | Version 3.001, Jan Tonellato / Synthview; unchanged `assets/fonts/fonnts.com-Novecento_sans_wide_Bold.otf` | Original embedded notice retained |

Novecento was acquired on 2026-10-19 from the [Fonnts distribution](https://fonnts.com/font_weights/novecento_sans_wide_bold-otf/). The original 77,356-byte OpenType file is retained unchanged. [Family reference](https://typography.synthview.com/novecento-sans-font-family.php).

## Public institution catalog and design references

`carsi-institutions.json` is a 2026-10-27 snapshot of 1,028 public institution records from [CARSI's catalog](https://ds.carsi.edu.cn/login/js/idpselect.js?t=20220407), linked by the [official login page](https://ds.carsi.edu.cn/login/index.html). Only public Chinese/English names and entity IDs are extracted; upstream JavaScript is not executed or bundled. Refresh it with source changes, not at startup.

The Institution picker uses project-owned DOM/CSS, informed by [Primer Autocomplete](https://primer.style/product/components/autocomplete/guidelines/) and [Spectrum Combo box](https://spectrum.adobe.com/fragments/components/combo-box/usage-guidelines). These component libraries are not bundled.

Journal covers are local user assets served by the saved-cover endpoint. Code licenses do not extend rights to third-party covers or marks. The application uses no remote font service at runtime.
