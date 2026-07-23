import type { ContentBlock } from "../types.ts";

export const industryBlocks: ContentBlock[] = [
  {
    type: "paragraph",
    text: "HBM 属于高度集中且极具壁垒的技术垄断市场。国内企业主要通过前工序半导体材料（前驱体/包封料）、后工序先进封装测试以及供应链代理参与产业链合作。",
    sourceIds: ["S-HBM-SHANNON-FILING", "S-HBM-YAKU-FILING", "S-HBM-TFME-FILING"],
  },
  {
    type: "bullets",
    items: [
      "前驱体材料：雅克科技作为半导体前驱体供应商，产品打入海外存储大厂供应链（公司口径）。",
      "颗粒塑封料：华海诚科推进 GMC 颗粒状塑封料研发与客户送样验证（公司口径）。",
      "存储分销：香农芯创授权代理 SK 海力士全线存储产品（公司口径）。",
      "先进封测：通富微电、长电科技具备大尺寸 2.5D/3D 先进封装能力，服务全球计算芯片巨头（公司口径）。",
    ],
    sourceIds: ["S-HBM-YAKU-FILING", "S-HBM-HUAHAI-FILING", "S-HBM-SHANNON-FILING", "S-HBM-TFME-FILING", "S-HBM-JCET-FILING"],
  },
  {
    type: "table",
    caption: "HBM A股生态圈合作环节与资质级别表",
    headers: ["环节", "产品/服务内容", "代表A股厂商", "事实/口径等级"],
    rows: [
      ["前驱体材料", "High-K前驱体与半导体化学品", "雅克科技", "公司口径（年报披露）"],
      ["塑封包封料", "GMC颗粒状塑封料研发", "华海诚科", "公司口径（年报披露）"],
      ["晶圆代理", "海力士HBM与企业级存储代理", "香农芯创", "公司口径（年报披露）"],
      ["后工序封测", "无锡后工序封测厂与2.5D封测", "太极实业、通富微电、长电科技", "公司口径（年报披露）"],
    ],
    sourceIds: ["S-HBM-YAKU-FILING", "S-HBM-HUAHAI-FILING", "S-HBM-SHANNON-FILING", "S-HBM-TAIJI-FILING", "S-HBM-TFME-FILING", "S-HBM-JCET-FILING"],
  },
];
