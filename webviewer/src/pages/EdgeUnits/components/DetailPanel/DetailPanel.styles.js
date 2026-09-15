import styled, { css } from 'styled-components';
import { em, rem } from 'styles';


export const Column = styled.div`
  display: flex;
  flex-direction: column;
  gap: ${em(12)};
`;

export const Heading = styled.h3`
  ${({ theme }) => css`
    margin: 0;
    font-family: ${theme.fonts.display};
    font-size: ${rem(16)};
    color: ${theme.colors.nature.n5};
  `}
`;

export const Tiles = styled.div`
  display: flex;
  gap: ${em(12)};
`;

export const Tile = styled.div`
  ${({ theme, $warn, $state }) => css`
    display: flex;
    flex-direction: column;
    gap: ${em(4)};
    min-width: ${em(100)};
    padding: ${em(10)} ${em(12)};
    background: ${theme.colors.nature.n0};
    border-radius: ${em(theme.radius[0])};
    box-shadow: ${theme.shadows()[0]};

    ${$warn &&
    css`
      color: ${theme.colors.status.silent};
    `}

    ${$state &&
    css`
      color: ${theme.colors.status[$state]};
    `}
  `}
`;

export const TileLabel = styled.span`
  ${({ theme }) => css`
    font-family: ${theme.fonts.mono};
    font-size: ${rem(10)};
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: ${theme.colors.nature.n4};
  `}
`;

export const TileValue = styled.span`
  font-size: ${rem(13)};
`;

export const AlertList = styled.ul`
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: ${em(6)};
`;

export const AlertItem = styled.li`
  ${({ theme, $severity }) => css`
    display: flex;
    align-items: baseline;
    gap: ${em(8)};
    padding: ${em(8)} ${em(10)};
    border-left: ${em(2)} solid ${theme.colors.status[$severity]};
    background: ${theme.colors.misc.background};
    font-size: ${rem(12)};
    color: ${theme.colors.nature.n5};
  `}
`;

export const ActivityLog = styled.ul`
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: ${em(6)};
`;

export const ActivityItem = styled.li`
  ${({ theme }) => css`
    display: flex;
    gap: ${em(8)};
    font-size: ${rem(12)};
    color: ${theme.colors.nature.n5};
  `}
`;

export const ActivityTime = styled.time`
  ${({ theme }) => css`
    font-family: ${theme.fonts.mono};
    color: ${theme.colors.nature.n3};
    flex: none;
  `}
`;

export const EmptyMessage = styled.p`
  ${({ theme }) => css`
    margin: 0;
    font-size: ${rem(12)};
    color: ${theme.colors.nature.n3};
  `}
`;

export const ImageFrame = styled.div`
  ${({ theme }) => css`
    aspect-ratio: 16 / 9;
    border-radius: ${em(theme.radius[0])};
    overflow: hidden;
    background: ${theme.colors.misc.background};

    img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
  `}
`;

export const ImagePlaceholder = styled(ImageFrame)`
  ${({ theme }) => css`
    display: flex;
    align-items: center;
    justify-content: center;
    padding: ${em(12)};
    text-align: center;
    font-size: ${rem(12)};
    color: ${theme.colors.nature.n3};
  `}
`;

export const Caption = styled.span`
  ${({ theme }) => css`
    font-family: ${theme.fonts.mono};
    font-size: ${rem(11)};
    color: ${theme.colors.nature.n3};
  `}
`;

export const ImageRetryRow = styled.div`
  ${({ theme }) => css`
    display: flex;
    align-items: center;
    gap: ${em(12)};
    color: ${theme.colors.danger};
    font-size: ${rem(12)};
  `}
`;
