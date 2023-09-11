import {gql, useApolloClient, useQuery} from '@apollo/client';
import {Box, Heading, Icon, MiddleTruncate, PageHeader} from '@dagster-io/ui-components';
import * as React from 'react';
import {Link} from 'react-router-dom';

import {useTrackPageView} from '../app/analytics';
import {displayNameForAssetKey, tokenForAssetKey} from '../asset-graph/Utils';
import {assetDetailsPathForKey} from '../assets/assetDetailsPathForKey';
import {AssetKey} from '../graphql/types';
import {useDocumentTitle} from '../hooks/useDocumentTitle';
import {useQueryPersistedState} from '../hooks/useQueryPersistedState';

import {OverviewTabs} from './OverviewTabs';
import {
  FailingAssetStatusFragment,
  FailingAssetsBaseQuery,
  FailingAssetsBaseQueryVariables,
  FailingAssetsAssetNodeFragment,
  FailingAssetsStatusQuery,
  FailingAssetsStatusQueryVariables,
} from './types/OverviewFailingAssetsRoot.types';

export const OverviewFailingAssetsRoot = () => {
  useTrackPageView();
  useDocumentTitle('Overview | Failing Assets');

  const data = useBatchedLoad();

  const [searchValue, setSearchValue] = useQueryPersistedState<string>({
    queryKey: 'search',
    defaults: {search: ''},
  });

  const failing = data.assetNodes.filter((a) => {
    const status = data.assetStatuses[toAssetKeyJSON(a)];
    return status && status.latestMaterialization?.runId !== status.latestRun?.id;
  });

  return (
    <Box flex={{direction: 'column'}} style={{height: '100%', overflow: 'hidden'}}>
      <PageHeader title={<Heading>Overview</Heading>} tabs={<OverviewTabs tab="failures" />} />
      {JSON.stringify(Object.keys(data.assetStatuses).length)}

      {failing.map((assetNode) => {
        return (
          <Box key={tokenForAssetKey(assetNode.assetKey)}>
            <h2>{displayNameForAssetKey(assetNode.assetKey)}</h2>
            <DownstreamBlastRadius assetKey={assetNode.assetKey} assetNodes={data.assetNodes} />
          </Box>
        );
      })}
    </Box>
  );
};

const DownstreamBlastRadius: React.FC<{
  assetKey: AssetKey;
  assetNodes: FailingAssetsAssetNodeFragment[];
}> = (props) => {
  const seen = new Set<string>();

  const renderEntryAndParents = (
    assetKey: AssetKey,
    depth: number,
    isFirstAtDepth: boolean,
  ): React.ReactNode[] => {
    const entryDisplayName = displayNameForAssetKey(assetKey);
    const entryLink = assetDetailsPathForKey(assetKey, {
      view: 'events',
    });

    // Safeguard against infinite loops in this code that could be caused by the
    // API returning an entry where assetKey === downstreamAssetKey
    if (seen.has(entryDisplayName)) {
      return [];
    }
    seen.add(entryDisplayName);

    const dependedByKeys =
      props.assetNodes.find((a) => displayNameForAssetKey(a.assetKey) === entryDisplayName)
        ?.dependedByKeys || [];

    return [
      <Box flex={{gap: 4}} style={{paddingLeft: Math.max(0, depth) * 20}} key={entryDisplayName}>
        {isFirstAtDepth && <Icon name="arrow_indent" style={{marginLeft: -20}} />}
        <Link to={entryLink}>
          <Box flex={{gap: 4}}>
            <Icon name="asset" />
            <MiddleTruncate text={entryDisplayName} />
          </Box>
        </Link>
      </Box>,
      ...dependedByKeys.map((e, idx) => renderEntryAndParents(e, depth + 1, idx === 0)),
    ];
  };

  return renderEntryAndParents(props.assetKey, 0, false);
};

function toAssetKeyJSON(a: {assetKey: {path: string[]}}) {
  return JSON.stringify({path: a.assetKey.path});
}

function useBatchedLoad() {
  const base = useQuery<FailingAssetsBaseQuery, FailingAssetsBaseQueryVariables>(
    FAILING_ASSETS_BASE_QUERY,
  );
  const [loaded, setLoaded] = React.useState<{[assetKeyJSON: string]: FailingAssetStatusFragment}>(
    {},
  );
  const client = useApolloClient();

  const assetKeyJSONs = React.useMemo(
    () => base.data?.assetNodes.map(toAssetKeyJSON).sort() || [],
    [base],
  );

  const missingKeysJSON = React.useMemo(
    () => JSON.stringify(assetKeyJSONs.filter((t) => !loaded[t]).slice(0, 100)),
    [assetKeyJSONs, loaded],
  );

  React.useEffect(() => {
    const run = async () => {
      const assetKeys = JSON.parse(missingKeysJSON).map((keyJSON: string) => JSON.parse(keyJSON));
      const {data} = await client.query<
        FailingAssetsStatusQuery,
        FailingAssetsStatusQueryVariables
      >({
        query: FAILING_ASSETS_STATUS_QUERY,
        variables: {assetKeys},
      });
      const result = Object.fromEntries(
        data.assetsLatestInfo.map((info) => [toAssetKeyJSON(info), info]),
      );
      setLoaded((loaded) => ({...loaded, ...result}));
    };
    run();
  }, [missingKeysJSON, client]);

  return {
    assetNodes: base.data?.assetNodes || [],
    assetStatuses: loaded,
  };
}

const FAILING_ASSETS_BASE_QUERY = gql`
  query FailingAssetsBaseQuery {
    assetNodes {
      ...FailingAssetsAssetNodeFragment
    }
  }

  fragment FailingAssetsAssetNodeFragment on AssetNode {
    id
    assetKey {
      path
    }
    dependedByKeys {
      path
    }
  }
`;

const FAILING_ASSETS_STATUS_QUERY = gql`
  query FailingAssetsStatusQuery($assetKeys: [AssetKeyInput!]!) {
    assetsLatestInfo(assetKeys: $assetKeys) {
      ...FailingAssetStatusFragment
    }
  }

  fragment FailingAssetStatusFragment on AssetLatestInfo {
    assetKey {
      path
    }
    latestMaterialization {
      runId
    }
    latestRun {
      id
    }
  }
`;
