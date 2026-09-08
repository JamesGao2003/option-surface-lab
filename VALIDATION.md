# Validation

Python rebuilt the site from the supplied raw options frame and checked unique contract/date keys, nonnegative finite observed prices and expiry dates. The corrected source pickle, option_pipeline_data_v2.pkl, is loaded using pandas compatibility support. All 442 RICs also passed the strict corrected suffix parser. The cache contains 182 observed calls and 179 observed puts, 81 candidates without observations, and zero unresolved requests.

The JavaScript check exercised all **118 date/type states** and compared both headline metrics with independently calculated Python reference values. It also verified finite 3D coordinates, no post-expiry points, both field toggles off, empty selection handling, complete HTML embedding and local artifact links.

Run `node validate_site.cjs` after rebuilding. Run the companion `data_quality_audit.ipynb` for the key data checks.

Result at the default Call / 2026-07-10 selection: 125 sampled active series; 36 mid-only; 28.8%; 73 paired records; median absolute difference $0.035.

No browser visual/rendering test or live GitHub Pages deployment has been performed. Confirm actual browser rendering, especially WebGL support for the 3D chart, after publication.
