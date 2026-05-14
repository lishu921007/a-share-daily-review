def classify(review: dict):
    up=review.get('up_ratio',0); med=review.get('median_pct_chg',0); main=review.get('main_net_mf_amount',0); pos=review.get('main_net_positive_ratio',0); lt3=review.get('lt_minus_3_ratio',0); gt3=review.get('gt_3_ratio',0)
    if up < .30 and med < -1 and lt3 > gt3 and main < 0:
        return '极端弱势','价格宽度极弱','资金明显流出','高'
    if up >= .65 and med > .5 and main > 0 and pos >= .5:
        return '强势环境','价格宽度强势','资金扩散偏强','低'
    if up >= .55 and med > 0 and main >= 0:
        return '中性偏强','价格宽度偏强','资金中性偏强','中低'
    if .45 <= up < .55 and -0.3 <= med <= .3:
        return '中性环境','价格宽度均衡','资金结构分化','中'
    if up < .45 and med < 0:
        return '弱势环境','价格宽度偏弱','资金承压','中高'
    return '结构性分化','价格宽度分化','资金结构分化','中'
