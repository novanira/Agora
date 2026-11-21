const OPTIMISE_URL = "https://agora-72bb.onrender.com/optimise";
const STORE_NAMES = {
    new_world: "New World",
    woolworths: "Woolworths",
    paknsave: "PAK'nSAVE",
};
export const SHORTLIST_SIZE = 3;
const currency = new Intl.NumberFormat("en-NZ", { style: "currency", currency: "NZD" });
const PACKAGE_UNITS = {
    mg: ["g", 0.001],
    g: ["g", 1],
    kg: ["g", 1000],
    ml: ["ml", 1],
    l: ["ml", 1000],
};

export function formatPrice(cents) {
    return currency.format(cents / 100);
}

export function productSize({ amount, quantity, unit }) {
    const size = quantity > 0 && unit && unit !== "pack" ? `${quantity} ${unit}` : "";
    const count = amount > 1 ? amount : unit === "pack" && quantity > 1 ? quantity : null;
    return [count && `${count} per pack`, size].filter(Boolean).join(" · ");
}

function readSavedArray(key) {
    try {
        const value = JSON.parse(localStorage.getItem(key) ?? "[]");
        return Array.isArray(value) ? value : [];
    } catch {
        return [];
    }
}

function queryKey(query) {
    return query.trim().toLowerCase();
}

function storeKey(chain, id) {
    return `${chain}:${id}`;
}

export function readBasketInputs() {
    const items = new Map();
    for (const saved of readSavedArray("agora-shopping-list")) {
        if (typeof saved !== "string" || !saved.trim()) continue;

        const query = saved.trim();
        const key = queryKey(query);
        const existing = items.get(key);
        if (existing) {
            existing.count += 1;
        } else {
            items.set(key, { key, query, count: 1 });
        }
    }

    const stores = new Map();
    for (const saved of readSavedArray("agora-selected-supermarkets")) {
        if (!Object.hasOwn(STORE_NAMES, saved?.chain)) continue;
        if (typeof saved.id !== "string" || !saved.id.trim()) continue;

        const { chain, id, name, address } = saved;
        const key = storeKey(chain, id.trim());
        stores.set(key, {
            key,
            chain,
            id: id.trim(),
            name: typeof name === "string" && name.trim() ? name.trim() : STORE_NAMES[chain],
            address: typeof address === "string" ? address.trim() : "",
        });
    }

    return { items: [...items.values()], stores: [...stores.values()] };
}

function listingId(value) {
    if (typeof value === "string") return value.trim();
    return Number.isSafeInteger(value) && value >= 0 ? String(value) : "";
}

function skuKey(chain, id) {
    return JSON.stringify([chain, id]);
}

function offerRef(store, id) {
    return JSON.stringify([store, id]);
}

function packageDetails({ amount, quantity, unit }) {
    const label = typeof unit === "string" ? unit.trim().toLowerCase() : "";
    const [measure, multiplier] = Object.hasOwn(PACKAGE_UNITS, label)
        ? PACKAGE_UNITS[label]
        : [label, 1];
    const hasQuantity = Number.isFinite(quantity) && quantity > 0;
    const count = Number.isFinite(amount) && amount > 0 ? amount : label === "pack" && hasQuantity ? quantity : null;
    const size = hasQuantity && measure && measure !== "pack" ? Number((quantity * multiplier).toPrecision(12)) : null;
    return { count, size, measure: size === null ? null : measure };
}

function compatiblePackages(a, b) {
    if (a.count !== null && b.count !== null && a.count !== b.count) return false;
    if (a.size === null || b.size === null) return true;
    if (a.measure !== b.measure) return false;
    if (a.size === b.size) return true;

    // The same multipack can list either the size of one unit or the total size.
    const count = a.count ?? b.count;
    return count > 1 && Number((Math.min(a.size, b.size) * count).toPrecision(12)) === Math.max(a.size, b.size);
}

function packageDetailCount({ size, count }) {
    return Number(size !== null) + Number(count !== null);
}

function recordIdentity(index, key, identity) {
    if (!index.has(key)) {
        index.set(key, identity);
    } else if (index.get(key) !== identity) {
        index.set(key, null);
    }
}

function indexMatches(matches, candidates) {
    const byRef = new Map();
    const bySku = new Map();
    const candidatesByRef = new Map(candidates.map((candidate) => [candidate.ref, candidate]));

    for (const match of Array.isArray(matches) ? matches : []) {
        if (!Array.isArray(match?.products)) continue;

        const linked = [];
        const barcodes = new Set();
        for (const reference of match.products) {
            const store = storeKey(reference?.supermarket, reference?.store_id);
            const id = listingId(reference?.product_id);
            const candidate = candidatesByRef.get(offerRef(store, id));
            if (!candidate) continue;

            linked.push(candidate);
            if (candidate.barcode) barcodes.add(candidate.barcode);
        }

        const barcode = listingId(match.barcode) || (barcodes.size === 1 ? [...barcodes][0] : "");
        const id = listingId(match.identity_id);
        const identity = barcode ? `barcode:${barcode}` : id && `identity:${id}`;
        if (!identity) continue;

        for (const candidate of linked) {
            if (candidate.barcode && barcode !== candidate.barcode) continue;
            recordIdentity(byRef, candidate.ref, identity);
            recordIdentity(bySku, candidate.sku, identity);
        }
    }

    for (const { sku, barcode } of candidates) {
        if (sku && barcode) recordIdentity(bySku, sku, `barcode:${barcode}`);
    }
    return { byRef, bySku };
}

function productChoice(key, candidates) {
    const offers = new Map();
    let representative = candidates[0];
    let rank = representative.rank;
    for (const candidate of candidates) {
        const current = offers.get(candidate.storeKey);
        if (!current || (candidate.available && (!current.available || candidate.unitCents < current.unitCents))) {
            offers.set(candidate.storeKey, candidate);
        }
        if (candidate.available) {
            const candidateDetails = packageDetailCount(candidate);
            const representativeDetails = packageDetailCount(representative);
            if (
                !representative.available || candidateDetails > representativeDetails ||
                (candidateDetails === representativeDetails && candidate.rank < representative.rank)
            ) representative = candidate;
        }
        rank = Math.min(rank, candidate.rank);
    }

    let availableCount = 0;
    let lowestUnitCents = null;
    for (const offer of offers.values()) {
        if (!offer.available) continue;
        availableCount += 1;
        if (lowestUnitCents === null || offer.unitCents < lowestUnitCents) lowestUnitCents = offer.unitCents;
    }
    return { key, product: representative.product, offers, availableCount, lowestUnitCents, rank };
}

function splitPackageVariants(group) {
    const variants = [];
    const ordered = [...group].sort((a, b) => packageDetailCount(b) - packageDetailCount(a));
    for (const candidate of ordered) {
        const matches = variants.filter((variant) => variant.every((other) => compatiblePackages(candidate, other)));
        // An incomplete package description cannot choose between conflicting pack sizes.
        const sameSku = matches.filter((variant) => variant.some((other) => (
            candidate.ref === other.ref || (candidate.sku && candidate.sku === other.sku)
        )));
        const suitable = sameSku.length === 1 ? sameSku[0] : matches.length === 1 ? matches[0] : null;
        if (suitable) suitable.push(candidate);
        else variants.push([candidate]);
    }
    return variants;
}

function groupProductChoices(candidates, matches) {
    const { byRef, bySku } = indexMatches(matches, candidates);
    const groups = new Map();

    for (const candidate of candidates) {
        const key = (candidate.barcode && `barcode:${candidate.barcode}`)
            || byRef.get(candidate.ref)
            || bySku.get(candidate.sku)
            || (candidate.sku ? `sku:${candidate.sku}` : candidate.ref);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(candidate);
    }

    const choices = [];
    for (const [key, group] of groups) {
        const variants = splitPackageVariants(group);
        for (const variant of variants) {
            const { size, measure, count, ref } = variant[0];
            const variantKey = variants.length === 1 ? key : JSON.stringify(["variant", key, size, measure, count, ref]);
            choices.push(productChoice(variantKey, variant));
        }
    }
    return choices.sort((a, b) => {
        const rankA = a.rank - Math.min(a.availableCount, 6);
        const rankB = b.rank - Math.min(b.availableCount, 6);
        return rankA - rankB || b.availableCount - a.availableCount;
    });
}

export function describeProductChoice({ key, offers }) {
    const evidence = new Map();
    for (const { sku, count, size, measure } of offers.values()) {
        evidence.set(JSON.stringify([sku, count, size, measure]), { sku, count, size, measure });
    }
    return { key, skuRefs: [...evidence.values()] };
}

export function resolveProductChoice(choices = [], selection) {
    if (typeof selection === "string") return choices.find(({ key }) => key === selection);
    if (!selection || typeof selection.key !== "string" || !Array.isArray(selection.skuRefs)) return;

    const refs = selection.skuRefs.filter((ref) => (
        typeof ref?.sku === "string" &&
        (ref.count === null || (Number.isFinite(ref.count) && ref.count > 0)) &&
        (ref.size === null || (Number.isFinite(ref.size) && ref.size > 0 && typeof ref.measure === "string"))
    ));
    const fitsPackage = ({ offers }) => [...offers.values()].every((offer) => (
        refs.every((ref) => compatiblePackages(offer, ref))
    ));
    const exact = choices.find(({ key }) => key === selection.key);
    if (exact && fitsPackage(exact)) return exact;

    const skus = new Set(refs.map(({ sku }) => sku).filter(Boolean));
    const compatible = choices.filter((choice) => fitsPackage(choice) && [...choice.offers.values()].some(({ sku }) => (
        skus.has(sku)
    )));
    if (compatible.length === 1) return compatible[0];
}

function buildCatalog(response, items, stores) {
    if (!Array.isArray(response?.stores)) {
        throw new Error("Unexpected optimisation response");
    }

    const productsByStore = new Map();
    for (const store of response.stores) {
        if (!store?.products || typeof store.products !== "object" || Array.isArray(store.products)) {
            continue;
        }

        const productsByQuery = new Map();
        for (const [query, products] of Object.entries(store.products)) {
            productsByQuery.set(queryKey(query), products);
        }
        productsByStore.set(storeKey(store.supermarket, store.store_id), productsByQuery);
    }

    const matchesByQuery = new Map(Object.entries(response.matches ?? {}).map(([query, matches]) => [queryKey(query), matches]));
    const productsByQuery = new Map();
    const automaticByQuery = new Map();
    for (const item of items) {
        const candidates = [];
        const automatic = new Map();
        for (const store of stores) {
            const products = productsByStore.get(store.key)?.get(item.key);
            if (!Array.isArray(products)) continue;

            let considered = 0;
            for (const [rank, product] of products.entries()) {
                if (typeof product?.name !== "string" || !product.name.trim()) continue;

                const id = listingId(product.product_id);
                const cents = Number.isFinite(product.price) && product.price >= 0
                    ? Math.round(product.price * 100)
                    : null;
                const unitCents = Number.isSafeInteger(cents) ? cents : null;
                const available = product.available === true && unitCents !== null;
                const candidate = {
                    product,
                    unitCents,
                    available,
                    rank,
                    storeKey: store.key,
                    barcode: listingId(product.barcode),
                    ref: id ? offerRef(store.key, id) : JSON.stringify(["listing", store.key, product.product_url, product.name, rank]),
                    sku: id ? skuKey(store.chain, id) : "",
                    ...packageDetails(product),
                };
                candidates.push(candidate);
                if (available && considered < SHORTLIST_SIZE) {
                    considered += 1;
                    if (!automatic.has(store.key) || unitCents < automatic.get(store.key).unitCents) automatic.set(store.key, candidate);
                }
            }
        }
        productsByQuery.set(item.key, groupProductChoices(candidates, matchesByQuery.get(item.key)));
        automaticByQuery.set(item.key, automatic);
    }

    return {
        items,
        stores: stores.map((store) => ({ ...store, hasResults: productsByStore.has(store.key) })),
        productsByQuery,
        automaticByQuery,
    };
}

export function buildBasket({ items, stores, productsByQuery, automaticByQuery }, selections = new Map()) {
    const branches = stores.map((store) => ({
        ...store,
        items: [],
        itemCount: 0,
        totalCents: 0,
    }));
    const splitByStore = new Map();
    const missing = [];
    let totalCents = 0;
    let itemCount = 0;

    for (const item of items) {
        const selection = selections.get(item.key);
        const offers = selection
            ? resolveProductChoice(productsByQuery.get(item.key), selection)?.offers
            : automaticByQuery.get(item.key);
        let cheapest = null;
        let cheapestStore = null;

        for (const branch of branches) {
            const offer = offers?.get(branch.key);
            if (!offer?.available) continue;

            const line = {
                ...item,
                product: offer.product,
                unitCents: offer.unitCents,
                totalCents: offer.unitCents * item.count,
            };
            branch.items.push(line);
            branch.itemCount += item.count;
            branch.totalCents += line.totalCents;

            if (!cheapest || line.totalCents < cheapest.totalCents) {
                cheapest = line;
                cheapestStore = branch;
            }
        }

        if (!cheapest) {
            missing.push(selection ? { ...item, reason: "selection-unavailable" } : item);
            continue;
        }

        if (!splitByStore.has(cheapestStore.key)) {
            const { key, name, address } = cheapestStore;
            splitByStore.set(key, { key, name, address, items: [], totalCents: 0 });
        }
        const group = splitByStore.get(cheapestStore.key);
        group.items.push(cheapest);
        group.totalCents += cheapest.totalCents;
        totalCents += cheapest.totalCents;
        itemCount += item.count;
    }

    return {
        groups: [...splitByStore.values()],
        branches: branches.sort((a, b) => b.itemCount - a.itemCount || a.totalCents - b.totalCents),
        missing,
        itemCount,
        totalCents,
    };
}

export async function fetchBasketCatalog(items, stores, signal) {
    const url = new URL(OPTIMISE_URL);
    for (const item of items) url.searchParams.append("query", item.query);
    for (const store of stores) url.searchParams.append(`${store.chain}_store_ids`, store.id);

    const response = await fetch(url, { signal });
    if (!response.ok) throw new Error(`Optimisation request failed (${response.status})`);

    return buildCatalog(await response.json(), items, stores);
}

export async function fetchOptimisedBasket(items, stores, signal) {
    return buildBasket(await fetchBasketCatalog(items, stores, signal));
}