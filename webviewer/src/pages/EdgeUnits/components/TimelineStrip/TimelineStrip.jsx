import React, { useMemo, useRef } from 'react';
import { formatInTimezone } from 'utils';
import {
  Wrapper,
  Bars,
  Bar,
  Axis,
  AxisLabel,
  Controls,
  RangeSelect
} from './TimelineStrip.styles';

const TICK_FRACTIONS = [0, 0.25, 0.5, 0.75, 1];

const ROLLING_AXIS_LABELS = ['−24 h', '−18', '−12', '−6', 'now'];

export const bucketBarState = value => {
  if (value >= 2) return 'ok';
  if (value === 1) return 'thin';
  return 'gap';
};

export const axisLabels = ({ from, to, timezone, rolling }) => {
  if (rolling) return ROLLING_AXIS_LABELS;
  if (!from || !to || !timezone) return [];

  const start = new Date(from).getTime();
  const durationMs = new Date(to).getTime() - start;

  return TICK_FRACTIONS.map(fraction =>
    formatInTimezone(new Date(start + fraction * durationMs), timezone, {
      hour: '2-digit',
      minute: '2-digit'
    })
  );
};

// -- selection ------------------------------------------------------

export const DROPDOWN_OPTIONS = [
  { value: 'whole-day', label: 'Whole day' },
  { value: 'morning', label: 'Morning' },
  { value: 'afternoon', label: 'Afternoon' },
  { value: 'evening', label: 'Evening' }
];

export const selectionForDrag = (anchorIndex, currentIndex) => {
  if (anchorIndex == null || currentIndex == null) return null;
  return {
    start: Math.min(anchorIndex, currentIndex),
    end: Math.max(anchorIndex, currentIndex)
  };
};

export const selectionOnRelease = range =>
  range && range.start !== range.end ? range : null;

export const isBucketOutsideSelection = (index, selectionRange) =>
  Boolean(selectionRange) && (index < selectionRange.start || index > selectionRange.end);

const CLOCK_BOUNDS = {
  morning: [6, 12],
  afternoon: [12, 18],
  evening: [18, 24]
};

const firstBucketAtOrAfterHour = ({
  from,
  bucketMinutes,
  bucketCount,
  timezone,
  targetHour
}) => {
  if (targetHour >= 24) return bucketCount;
  const start = new Date(from).getTime();
  for (let index = 0; index < bucketCount; index++) {
    const bucketInstant = new Date(start + index * bucketMinutes * 60000);
    // % 24: some ICU versions format midnight as "24", not "00".
    const hour =
      Number(
        formatInTimezone(bucketInstant, timezone, { hour: '2-digit', hour12: false })
      ) % 24;
    if (hour >= targetHour) return index;
  }
  return bucketCount;
};

export const dropdownRange = (
  value,
  { from, bucketMinutes, bucketCount, timezone, rolling }
) => {
  if (rolling || value === 'whole-day' || !CLOCK_BOUNDS[value]) return null;
  if (!from || !bucketMinutes || !bucketCount || !timezone) return null;

  const [startHour, endHour] = CLOCK_BOUNDS[value];
  const start = firstBucketAtOrAfterHour({
    from,
    bucketMinutes,
    bucketCount,
    timezone,
    targetHour: startHour
  });
  const end =
    firstBucketAtOrAfterHour({
      from,
      bucketMinutes,
      bucketCount,
      timezone,
      targetHour: endHour
    }) - 1;

  if (start > end) return null;
  return { start, end: Math.min(end, bucketCount - 1) };
};

export const bucketRangeToTimeRange = (selectionRange, { from, bucketMinutes }) => {
  if (!selectionRange || !from || !bucketMinutes) return null;
  const start = new Date(from).getTime();
  const bucketMs = bucketMinutes * 60000;
  return {
    start: start + selectionRange.start * bucketMs,
    end: start + (selectionRange.end + 1) * bucketMs
  };
};

// A committed range can be stale (window moved on) - check before fetching.
export const isTimeRangeWithinWindow = (timeRange, from, to) => {
  if (!timeRange || !from || !to) return false;
  const start = new Date(from).getTime();
  const end = new Date(to).getTime();
  return timeRange.start >= start && timeRange.end <= end;
};

const dropdownValueFor = (selectionRange, optionRanges) => {
  if (!selectionRange) return 'whole-day';
  const match = Object.entries(optionRanges).find(
    ([, range]) =>
      range && range.start === selectionRange.start && range.end === selectionRange.end
  );
  return match ? match[0] : 'whole-day';
};

export const TimelineChart = ({
  telemetryUnits,
  selectedUnitId,
  from,
  to,
  bucketMinutes,
  timezone,
  rolling,
  selectionRange,
  onSelectionChange,
  onSelectionCommit
}) => {
  const anchorRef = useRef(null);

  const telemetryUnit = useMemo(
    () => (telemetryUnits ?? []).find(unit => unit.unit_id === selectedUnitId),
    [telemetryUnits, selectedUnitId]
  );
  const buckets = telemetryUnit?.buckets ?? [];

  const labels = useMemo(
    () => axisLabels({ from, to, timezone, rolling }),
    [from, to, timezone, rolling]
  );

  const bucketCount = buckets.length;
  const optionRanges = useMemo(
    () => ({
      morning: dropdownRange('morning', {
        from,
        bucketMinutes,
        bucketCount,
        timezone,
        rolling
      }),
      afternoon: dropdownRange('afternoon', {
        from,
        bucketMinutes,
        bucketCount,
        timezone,
        rolling
      }),
      evening: dropdownRange('evening', {
        from,
        bucketMinutes,
        bucketCount,
        timezone,
        rolling
      })
    }),
    [from, bucketMinutes, bucketCount, timezone, rolling]
  );

  const indexFromEvent = event => {
    const target = document.elementFromPoint(event.clientX, event.clientY);
    const index = target?.dataset?.index;
    return index == null ? null : Number(index);
  };

  const handlePointerDown = event => {
    const index = indexFromEvent(event);
    if (index == null) return;
    anchorRef.current = index;
    try {
      // Can throw if the pointer's no longer active - not fatal.
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // no-op
    }
    onSelectionChange(selectionForDrag(index, index));
  };

  const handlePointerMove = event => {
    if (anchorRef.current == null) return;
    const index = indexFromEvent(event);
    if (index == null) return;
    onSelectionChange(selectionForDrag(anchorRef.current, index));
  };

  const handlePointerUp = () => {
    if (anchorRef.current == null) return;
    anchorRef.current = null;
    const next = selectionOnRelease(selectionRange);
    onSelectionChange(next);
    onSelectionCommit(next);
  };

  const handleDropdownChange = event => {
    const { value } = event.target;
    const next = value === 'whole-day' ? null : optionRanges[value] ?? null;
    onSelectionChange(next);
    onSelectionCommit(next);
  };

  return (
    <Wrapper>
      <Bars
        role='img'
        aria-label={`Telemetry coverage for ${selectedUnitId ?? 'the selected unit'}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        {buckets.map((value, index) => (
          <Bar
            key={index}
            data-index={index}
            $state={bucketBarState(value)}
            $isOutside={isBucketOutsideSelection(index, selectionRange)}
          />
        ))}
      </Bars>
      <Axis>
        {labels.map((label, index) => (
          <AxisLabel key={index}>{label}</AxisLabel>
        ))}
      </Axis>
      <Controls>
        <RangeSelect
          aria-label='Select a time window'
          value={dropdownValueFor(selectionRange, optionRanges)}
          onChange={handleDropdownChange}
        >
          {DROPDOWN_OPTIONS.map(option => (
            <option
              key={option.value}
              value={option.value}
              disabled={rolling && option.value !== 'whole-day'}
            >
              {option.label}
            </option>
          ))}
        </RangeSelect>
      </Controls>
    </Wrapper>
  );
};
