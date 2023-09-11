// Generated GraphQL types, do not edit manually.

import * as Types from '../../graphql/types';

export type FailingAssetsBaseQueryVariables = Types.Exact<{[key: string]: never}>;

export type FailingAssetsBaseQuery = {
  __typename: 'Query';
  assetNodes: Array<{
    __typename: 'AssetNode';
    id: string;
    assetKey: {__typename: 'AssetKey'; path: Array<string>};
    dependedByKeys: Array<{__typename: 'AssetKey'; path: Array<string>}>;
  }>;
};

export type FailingAssetsAssetNodeFragment = {
  __typename: 'AssetNode';
  id: string;
  assetKey: {__typename: 'AssetKey'; path: Array<string>};
  dependedByKeys: Array<{__typename: 'AssetKey'; path: Array<string>}>;
};

export type FailingAssetsStatusQueryVariables = Types.Exact<{
  assetKeys: Array<Types.AssetKeyInput> | Types.AssetKeyInput;
}>;

export type FailingAssetsStatusQuery = {
  __typename: 'Query';
  assetsLatestInfo: Array<{
    __typename: 'AssetLatestInfo';
    assetKey: {__typename: 'AssetKey'; path: Array<string>};
    latestMaterialization: {__typename: 'MaterializationEvent'; runId: string} | null;
    latestRun: {__typename: 'Run'; id: string} | null;
  }>;
};

export type FailingAssetStatusFragment = {
  __typename: 'AssetLatestInfo';
  assetKey: {__typename: 'AssetKey'; path: Array<string>};
  latestMaterialization: {__typename: 'MaterializationEvent'; runId: string} | null;
  latestRun: {__typename: 'Run'; id: string} | null;
};
