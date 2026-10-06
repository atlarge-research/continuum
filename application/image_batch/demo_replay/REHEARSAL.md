# Presentation walkthrough and rehearsal

## Suggested walkthrough — about three minutes

1. **Presenter's introduction — 35 seconds.** “This is a compute-side component of the 6G digital twin and DevOps ecosystem. Incoming image data is processed by real workers. This capture uses KPN 5G trace emulation; partner network-twin integration follows later. We replay the observations, forecasts, decisions and physical response from a completed run.”
2. **Overview — 20 seconds.** “Worker bands show CPU and RAM requests, grouped by job phase; blue markers show measured application use. Powered reserves can accept work when admission changes. The service indicator separates confirmed deadline outcomes from pending work.”
3. **Demand and decision — 30 seconds.** Choose **Demand rises**, briefly play, then choose **Scale-up decision**. “The twin forecasts arrivals and compares simulated service and capacity allocation. These are the historical alternatives and recorded choice.”
4. **Physical response — 25 seconds.** Choose **Scale-up confirmed**. “The worker was powered already. Admission was requested, delayed, then observed. Every playback panel shares this time.”
5. **Policy comparison — 35 seconds.** “Static keeps capacity fixed. The heuristic responds to measured demand. The twin forecasts and evaluates options, making future demand and possible actions visible before deciding. All three policies meet the target. Both dynamic policies use less application allocation than static, and the twin uses less than the heuristic. The heuristic has faster response p95 than the twin. These are selected development results; allocation is not energy or total powered-worker cost.”
6. **Optional Analysis — 20 seconds.** Open Analysis, select an issued forecast and briefly play to show actual observations accumulating; **Latest** restores following publications. Expand explanations only for a technical question. Return to Overview.

Use bookmarks to keep the conversation short. Use the displayed duration; at 16× the operating trace takes about one minute. Comparison results describe completed runs and do not change with the playback cursor. The accepted comparison contains one matched workload; do not present the tested heuristic rule as every industry's autoscaler.

## Controls and display

- **Seek backward:** drag the timeline left or choose an earlier bookmark. Seeking pauses and rebuilds the visible state from the evidence; it does not run the experiment backward.
- **Views:** Overview and Analysis preserve playback time, speed and play/pause state. Policy comparison pauses the replay and hides the time bar because its completed-run results are independent of playback. Returning to Overview or Analysis restores the time bar at the retained time and speed, paused. Playback keyboard shortcuts are inactive on comparison. Returning to a view starts its content at the top.
- **Small windows / browser zoom:** scroll inside the content area when the “Scroll ↓” hint appears. Playback controls remain visible on Overview and Analysis. Policy comparison uses that space for policy explanations and its takeaway. Use Chrome full screen on the monitor, then adjust zoom if needed; 16:9 is a useful expectation, not a verified venue specification.
- **Offline:** download the replay HTML beforehand. It contains everything it needs. A second local copy is a useful presentation backup.

## Laptop and venue acceptance

The presenter reported a **MacBook Pro using Chrome** and confirmed that earlier replay artifacts opened locally, including play/pause, restart, speed and bookmarks. Each revised delivery still needs a quick local check.

- Open the current HTML locally in Chrome with networking disabled.
- Check Overview readability, worker resource bands and service status; check all three views and their scroll access.
- Try the timeline to the right and then left; verify every visible panel returns to the earlier time.
- Try Play/pause, Restart, speed and the demand/decision/response bookmarks. While playing, open Policy comparison; confirm the time bar disappears and the comparison fits. Return to Overview; confirm playback is paused at the retained time and speed.
- Run the walkthrough in no more than three minutes, using your own introductory slides.
- On arrival, check the actual monitor, scaling, zoom and readability from approximately three metres.

Record the rehearsal date, duration and any observed issue here. Venue resolution and lighting remain unknown.
