import React, { useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import { Header as PageHeader } from 'components/Header';
import { Skeleton } from 'components/_shared/Skeleton';
import { Button } from 'components/_shared/Button';
import {
  useGetUnitsQuery,
  useGetUnitsTelemetryQuery,
  useGetUnitLatestImageUrlQuery,
  selectUserTimezone
} from 'state';
import { useFleetStatus } from 'hooks';
import { getAccountToday, shiftDate } from 'utils';
import {
  AccountHeader,
  FleetStatus,
  FilterChips,
  DayBar,
  UnitCards,
  UnitsMap,
  TimelineChart,
  bucketRangeToTimeRange,
  isTimeRangeWithinWindow,
  SummaryRow,
  DetailPanel
} from './components';
import {
  PageContainer,
  StatusLine,
  ChipsRow,
  DayBarRow,
  UnitCardsStrip,
  MapArea,
  TimelineStrip,
  DetailPanelSection,
  CardsSkeletonRow,
  RetryRow
} from './EdgeUnits.styles';

const POLLING_INTERVAL_MS = 30000;
const IMAGE_POLLING_INTERVAL_MS = 5 * 60 * 1000;
const MIN_UNITS_FOR_CHIPS = 6;

const Section = ({ isLoading, isError, onRetry, skeleton, children }) => {
  if (isLoading) return skeleton;
  if (isError) {
    return (
      <RetryRow>
        <span>Failed to load.</span>
        <Button onClick={onRetry}>Retry</Button>
      </RetryRow>
    );
  }
  return children ?? null;
};

export const EdgeUnits = () => {
  const timezone = useSelector(selectUserTimezone);
  const today = timezone ? getAccountToday(timezone) : null;

  const [day, setDay] = useState(null);
  const [rolling, setRolling] = useState(true);
  const [stateFilter, setStateFilter] = useState('all');
  const [selectedUnitId, setSelectedUnitId] = useState(null);
  const [selectionRange, setSelectionRange] = useState(null);
  const [committedSelectionRange, setCommittedSelectionRange] = useState(null);
  const [committedSelectionContext, setCommittedSelectionContext] = useState(null);

  const resolvedDay = day ?? today;
  const windowArgs = rolling ? { rolling: true } : { day: resolvedDay };
  const isLiveWindow = rolling || resolvedDay === today;
  const selectionContext = `${resolvedDay}|${rolling}|${selectedUnitId}`;

  const {
    data: unitsData,
    isLoading: isUnitsLoading,
    isError: isUnitsError,
    refetch: refetchUnits
  } = useGetUnitsQuery();

  const {
    data: telemetryData,
    isLoading: isTelemetryLoading,
    isError: isTelemetryError,
    refetch: refetchTelemetry
  } = useGetUnitsTelemetryQuery(windowArgs, {
    skip: !rolling && !resolvedDay,
    pollingInterval: isLiveWindow ? POLLING_INTERVAL_MS : 0
  });

  const fleetStatus = useFleetStatus(unitsData?.units, telemetryData?.units);

  const visibleUnits = useMemo(
    () =>
      (unitsData?.units ?? []).filter(
        unit =>
          stateFilter === 'all' || fleetStatus.stateByUnitId[unit.unit_id] === stateFilter
      ),
    [unitsData, stateFilter, fleetStatus.stateByUnitId]
  );

  // Don't leave a filter active once the chip row that set it is hidden.
  useEffect(() => {
    if (fleetStatus.counts.all < MIN_UNITS_FOR_CHIPS && stateFilter !== 'all') {
      setStateFilter('all');
    }
  }, [fleetStatus.counts.all, stateFilter]);

  // Reset selection if it's no longer in visibleUnits.
  useEffect(() => {
    if (visibleUnits.some(unit => unit.unit_id === selectedUnitId)) return;
    setSelectedUnitId(visibleUnits[0]?.unit_id ?? null);
  }, [visibleUnits, selectedUnitId]);

  useEffect(() => {
    setSelectionRange(null);
    setCommittedSelectionRange(null);
    setCommittedSelectionContext(null);
  }, [resolvedDay, rolling, selectedUnitId, telemetryData?.from, telemetryData?.to]);

  const selectionTimeRange = useMemo(
    () =>
      bucketRangeToTimeRange(selectionRange, {
        from: telemetryData?.from,
        bucketMinutes: telemetryData?.bucket_minutes
      }),
    [selectionRange, telemetryData?.from, telemetryData?.bucket_minutes]
  );

  const committedTimeRange = useMemo(
    () =>
      bucketRangeToTimeRange(committedSelectionRange, {
        from: telemetryData?.from,
        bucketMinutes: telemetryData?.bucket_minutes
      }),
    [committedSelectionRange, telemetryData?.from, telemetryData?.bucket_minutes]
  );

  // telemetryData lags a render behind day/rolling/unit switches, so it
  // can't catch those alone - selectionContext catches the switch, the
  // time-range check catches rolling mode's own poll drift.
  const isCommittedRangeValid =
    committedSelectionRange != null &&
    committedSelectionContext === selectionContext &&
    isTimeRangeWithinWindow(committedTimeRange, telemetryData?.from, telemetryData?.to);

  const { data: rangeTelemetryData } = useGetUnitsTelemetryQuery(
    {
      ...windowArgs,
      unitId: selectedUnitId,
      rangeFrom: isCommittedRangeValid
        ? new Date(committedTimeRange.start).toISOString()
        : undefined,
      rangeTo: isCommittedRangeValid
        ? new Date(committedTimeRange.end).toISOString()
        : undefined
    },
    { skip: !isCommittedRangeValid || !selectedUnitId }
  );

  const {
    data: latestImage,
    isLoading: isLatestImageLoading,
    error: latestImageError,
    refetch: refetchLatestImage
  } = useGetUnitLatestImageUrlQuery(
    { unitId: selectedUnitId },
    {
      skip: !selectedUnitId,
      pollingInterval: isLiveWindow ? IMAGE_POLLING_INTERVAL_MS : 0
    }
  );

  const selectedUnit = visibleUnits.find(unit => unit.unit_id === selectedUnitId);
  const selectedTelemetryUnit = telemetryData?.units?.find(
    unit => unit.unit_id === selectedUnitId
  );
  const summaryTotals = isCommittedRangeValid
    ? rangeTelemetryData?.units?.[0]?.totals
    : selectedTelemetryUnit?.totals;
  const activityTrack = isCommittedRangeValid
    ? rangeTelemetryData?.units?.[0]?.track
    : selectedTelemetryUnit?.track;

  const handleSelectionCommit = range => {
    setCommittedSelectionRange(range);
    setCommittedSelectionContext(selectionContext);
  };

  const handleRetryOverview = () => {
    refetchUnits();
    refetchTelemetry();
  };

  const handlePrevDay = () => {
    setRolling(false);
    setDay(shiftDate(resolvedDay, -1));
  };

  const handleNextDay = () => {
    if (rolling || resolvedDay >= today) return;
    setRolling(false);
    setDay(shiftDate(resolvedDay, 1));
  };

  const handleSelectDay = iso => {
    setRolling(false);
    setDay(iso);
  };

  const handleToday = () => {
    setRolling(false);
    setDay(today);
  };

  const handleToggleRolling = () => setRolling(value => !value);

  return (
    <div>
      <PageHeader />
      <PageContainer>
        <AccountHeader />
        <StatusLine data-testid='status-line'>
          <Section
            isLoading={isUnitsLoading || isTelemetryLoading}
            isError={isUnitsError || isTelemetryError}
            onRetry={handleRetryOverview}
            skeleton={<Skeleton height='20px' />}
          >
            <FleetStatus fleetStatus={fleetStatus} isLiveWindow={isLiveWindow} />
          </Section>
        </StatusLine>
        <ChipsRow data-testid='filter-chips'>
          <Section
            isLoading={isUnitsLoading || isTelemetryLoading}
            isError={isUnitsError || isTelemetryError}
            onRetry={handleRetryOverview}
            skeleton={<Skeleton height='24px' width='240px' />}
          >
            <FilterChips
              counts={fleetStatus.counts}
              stateFilter={stateFilter}
              onChangeFilter={setStateFilter}
            />
          </Section>
        </ChipsRow>
        <DayBarRow data-testid='day-bar'>
          <Section
            isLoading={isUnitsLoading || !today}
            isError={isUnitsError}
            onRetry={refetchUnits}
            skeleton={<Skeleton height='32px' />}
          >
            <DayBar
              day={resolvedDay}
              today={today}
              rolling={rolling}
              onPrevDay={handlePrevDay}
              onNextDay={handleNextDay}
              onSelectDay={handleSelectDay}
              onToday={handleToday}
              onToggleRolling={handleToggleRolling}
            />
          </Section>
        </DayBarRow>
        <UnitCardsStrip data-testid='unit-cards'>
          <Section
            isLoading={isUnitsLoading || isTelemetryLoading}
            isError={isUnitsError || isTelemetryError}
            onRetry={handleRetryOverview}
            skeleton={
              <CardsSkeletonRow>
                <Skeleton height='90px' width='160px' />
                <Skeleton height='90px' width='160px' />
                <Skeleton height='90px' width='160px' />
              </CardsSkeletonRow>
            }
          >
            <UnitCards
              units={visibleUnits}
              telemetryUnits={telemetryData?.units}
              stateByUnitId={fleetStatus.stateByUnitId}
              selectedUnitId={selectedUnitId}
              onSelectUnit={setSelectedUnitId}
            />
          </Section>
        </UnitCardsStrip>
        <MapArea data-testid='map-area'>
          <Section
            isLoading={isUnitsLoading || isTelemetryLoading}
            isError={isUnitsError || isTelemetryError}
            onRetry={handleRetryOverview}
            skeleton={<Skeleton height='360px' />}
          >
            <UnitsMap
              units={visibleUnits}
              telemetryUnits={telemetryData?.units}
              stateByUnitId={fleetStatus.stateByUnitId}
              selectedUnitId={selectedUnitId}
              onSelectUnit={setSelectedUnitId}
              timezone={timezone}
              resolvedDay={resolvedDay}
              rolling={rolling}
              selectionTimeRange={selectionTimeRange}
            />
          </Section>
        </MapArea>
        <TimelineStrip data-testid='timeline-strip'>
          <Section
            isLoading={isTelemetryLoading}
            isError={isTelemetryError}
            onRetry={refetchTelemetry}
            skeleton={<Skeleton />}
          >
            <TimelineChart
              telemetryUnits={telemetryData?.units}
              selectedUnitId={selectedUnitId}
              from={telemetryData?.from}
              to={telemetryData?.to}
              bucketMinutes={telemetryData?.bucket_minutes}
              timezone={timezone}
              rolling={rolling}
              selectionRange={selectionRange}
              onSelectionChange={setSelectionRange}
              onSelectionCommit={handleSelectionCommit}
            />
            <SummaryRow totals={summaryTotals} timezone={timezone} />
          </Section>
        </TimelineStrip>
        <DetailPanelSection data-testid='detail-panel'>
          <Section
            isLoading={isTelemetryLoading}
            isError={isTelemetryError}
            onRetry={refetchTelemetry}
            skeleton={<Skeleton />}
          >
            <DetailPanel
              unit={selectedUnit}
              telemetryUnit={selectedTelemetryUnit}
              activityTrack={activityTrack}
              state={fleetStatus.stateByUnitId[selectedUnitId]}
              timezone={timezone}
              latestImage={latestImage}
              isLatestImageLoading={isLatestImageLoading}
              latestImageError={latestImageError}
              onRetryLatestImage={refetchLatestImage}
            />
          </Section>
        </DetailPanelSection>
      </PageContainer>
    </div>
  );
};
