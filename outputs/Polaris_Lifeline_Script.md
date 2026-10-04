# Polaris Lifeline: 5-minute pitch script

Team Polaris · Challenge 3. Five speakers: replace **Speaker 1** to **Speaker 5** with your names.
Timing is at 130 words per minute. The deck is `outputs/Polaris_Lifeline_Pitch.pptx`; each slide's lines are also in its speaker notes.

## Timing

| Speaker | Section | Slides | Words | Time |
|---|---|---|---|---|
| Speaker 1 | Story and problem | 1, 2, 3 | 125 | 0:58 |
| Speaker 2 | Problem definition and solution | 4, 5 | 133 | 1:01 |
| Speaker 3 | How it works and results | 6, 7, 8 | 145 | 1:07 |
| Speaker 4 | Live demo | 9 | 129 | 1:00 |
| Speaker 5 | Reflection and close | 10, 11 | 113 | 0:52 |
| **Total** | | | **645** | **4:58** |

The 5:00 assumes Speaker 4 clicks while talking (the demo lines take 1:00). Rehearse the clicks: any pause adds to the total.

## Speaker 1: Story and problem

**Slide 1: Polaris Lifeline**

Hi everyone. We're Team Polaris, and this is Polaris Lifeline.

**Slide 2: May 2022. Hay River, NT.**

May 2022, Hay River. The spring ice jammed at the mouth of the river, and water backed up into town. About 3,500 people were ordered to evacuate. Around 500 homes, businesses and community buildings were damaged. Recovery is estimated at 93.6 million dollars, and only a handful had flood insurance. Everyone got out safely.

**Slide 3: It keeps happening**

And it keeps happening: five communities in 2021, then Hay River. Help has to come by road, air or boat, and breakup closes the ice roads and ferries. Today, the territory publishes break-up reports from gauges, cameras and satellite images, and the town issues an evacuation notice once officials see breakup inside town. That's the river now, not what's coming. [Speaker 2]?

*Handoff to Speaker 2*

## Speaker 2: Problem definition and solution

**Slide 4: The problem, defined**

Our goal: predict the chance of an ice-jam flood before it happens, with RCM satellite radar at the core. We set six objectives. Days of warning, not hours. Show where in town is at risk. Few false alarms and missed floods. Work in other towns. Be clear to responders. And need no equipment in the field. Our limits: only EODMS and open data, very few past floods to learn from, and a new image only every few days.

**Slide 5: Polaris Lifeline**

Our answer is Polaris Lifeline. Most satellite tools map a flood after it happens. We read the ice that causes the flood, before it happens. It's built for first responders, emergency managers and community leaders. We weighed four approaches against these goals, and we'll compare them after the demo. Here's [Speaker 3] on how it works.

*Handoff to Speaker 3*

## Speaker 3: How it works and results

**Slide 6: How it works**

Two parts. First, the ice. RCM radar sees through cloud and darkness, and jammed ice shows up bright. Our rules turn each image into a map of open water, smooth ice and jammed ice. Second, a statistical model trained on 46 past springs forecasts the peak river level. If the radar sees a jam, the risk goes up a level.

**Slide 7: Flood year vs normal year**

We set that rule with a flood year and a normal year: over 90 percent jammed ice in 2022, never above 76 in 2023. Our line sits halfway.

**Slide 8: Does it work?**

Does it work? Tested on springs it never saw, it rated all five flood years Warning or higher a week ahead. In 2022, High danger came three weeks early. The trade-off: one in three normal springs also got a Warning. And twelve predictions on two new rivers are locked, not yet scored. [Speaker 4], show us the tool.

*Handoff to Speaker 4*

## Speaker 4: Live demo

**Slide 9: Live demo**

This is our live tool. Hay River at the peak: the 2022 flood year on the left, 2023, a normal year, on the right. Blue is open water, white is smooth ice, amber is jammed ice, and red is land we estimate flooded. A few days earlier, 2022 is already jammed solid. 2023 isn't. Afterwards, 2023 clears out. Below is the prediction: a risk level, a confidence, and one sentence on why. Now the responder view. Pick any day since 2021, and it shows what we would have said that day. May 8, 2022: High danger, breakup any day now. Every building is coloured by risk, and the side panel lists neighbourhoods, routes and facilities by danger. Zoom out, and you see every site at once. Back to [Speaker 5].

*Open web/how-it-works.html (Peak selected) > click Before peak > click After peak > scroll to Prediction > click 'Back to the map' (index.html) > set day 2022-05-08 > zoom out with the globe button. If the demo fails, go to the hidden backup slide 9b.*

## Speaker 5: Reflection and close

**Slide 10: Did we solve it?**

Did we meet our goals? Lead time: met, weeks of warning in 2022. Where: partly, our flood map is an estimate, for Hay River only. Reliability: partly, every tested flood caught, but with false alarms. Transferability: waiting on the blind test. Clarity: built for responders, not yet tested with them. And no field equipment. The alternatives: sensors only see water once it rises, flood maps come too late, and a gauge-only model can't see the ice.

**Slide 11: What's next**

Next: process every new RCM pass automatically, send alerts to emergency managers, add more rivers, and build it with the people who'll use it. So the next Hay River gets days of warning, not hours. Thank you.

## Q&A prep

**Why RCM instead of Sentinel-1?**  
RCM is the challenge requirement, and it's Canada's own constellation built for watching the North. We used 16 m images with two polarizations. Our rules read radar brightness, so Sentinel-1 could fill gaps later.

**How accurate is it really?**  
Tested on springs it never saw: all 5 flood years were rated Warning or higher a week ahead. 10 of 32 normal springs also got a Warning, none Critical. Peak-level error a week out is 1.41 m, against 1.68 m for guessing the average. We chose to be cautious: a missed flood costs more than a false alarm.

**What does RCM add, if the forecast uses river gauges?**  
RCM shows whether a jam is physically forming near town. In 2022 the river forecast was already at Critical, and RCM confirmed it: 91 to 95 percent jammed ice. At new sites without long gauge records, like our blind-test rivers, RCM is the only input.

**Doesn't the GNWT already look at RCM images?**  
Yes, and that's a strength for us: its spring break-up reports include RCM and optical satellite images, gauge readings and camera photos, interpreted by experts. Those reports describe conditions as they are. Polaris Lifeline reads the RCM images automatically and turns them, with river and weather data, into a daily flood risk with days of lead time and a list of places at risk.

**What happens when RCM has no image that week?**  
The forecast still updates daily from river flow, lake level and ice thickness. Confidence drops from High to Medium, because High needs an image from the last three days.

**How would a first responder actually receive this?**  
Today, a web map: pick a day and see the risk level, the confidence, and a list of neighbourhoods, routes and facilities by danger. Next step: automatic alerts to emergency managers when a new RCM pass raises the risk.

**What were the blind-test misses, and why?**  
We haven't scored it yet, on purpose. The predictions for Fort Simpson and the Albany River were locked with timestamps and fingerprints before anyone looked at outcomes. We already flagged lower confidence there: wider rivers, different beams, and a tidal estuary at Albany. [PLACEHOLDER: hits and misses after scoring.]

**Is this really machine learning? Why not deep learning?**  
The forecast is a ridge regression trained on 46 springs, and the ice map uses fixed radar rules. There are only five flood years on record, so a deep model would just memorise them. We chose a model where every number can be explained to a responder.

**How good is the flood map?**  
It's an estimate from 2020 lidar elevation and a sloping ice-jam water surface. For 2022 it covers 58 percent of the flooding mapped from RCM and 77 percent of NRCan's mapped flooding, but it also marks a lot of land that stayed dry, so we call it an estimate and use it to rank places, not to draw exact lines.

## Notes for the team

- **Placeholder:** blind-test hits and misses (backup slide 16 and Q&A) until the blind test is scored.
- **Not yet checked:** the 2021 figure (five NWT communities). Its source is kept closed until the blind test is scored, because it may describe a blind-test site. It's marked † on slide 3.
- **Fonts:** install `outputs/pitch_assets/fonts/` (Lato, Noto Sans) on the presenting laptop, or PowerPoint will substitute other fonts.
- **Demo:** open `web/how-it-works.html` before you start; the map needs internet for its background tiles.
- Slide 9b (demo screenshots) is hidden: jump to it only if the live demo fails.
