// Basic visualizer for OSINT data
function renderGraph(data) {
    const nodes = [];
    const edges = [];
    const formattedData = {};

    // Simplistic node generation
    if (Array.isArray(data)) {
        data.forEach(row => {
            if (!row || typeof row !== 'object') return;
            
            const sourceUrl = row.SourceURL;
            const entities = row.Entities;

            if (sourceUrl && !formattedData[sourceUrl]) {
                try {
                    formattedData[sourceUrl] = { id: sourceUrl, label: new URL(sourceUrl).hostname, group: "domain" };
                    nodes.push(formattedData[sourceUrl]);
                } catch (e) {
                    // Fallback if URL parsing fails
                    formattedData[sourceUrl] = { id: sourceUrl, label: sourceUrl, group: "domain" };
                    nodes.push(formattedData[sourceUrl]);
                }
            }

            if (entities) {
                // Check if entities is a string (JSON) or object
                let entityObj = entities;
                if (typeof entities === 'string') {
                    try { entityObj = JSON.parse(entities); } catch (e) { }
                }

                if (entityObj && typeof entityObj === 'object') {
                    for (const [type, list] of Object.entries(entityObj)) {
                        // Ensure list is an array before calling forEach
                        const entityList = Array.isArray(list) ? list : (typeof list === 'string' ? [list] : []);
                        entityList.forEach(val => {
                            if (!val) return; // Skip empty values
                            const nodeId = `${type}:${val}`;
                            if (!formattedData[nodeId]) {
                                formattedData[nodeId] = { id: nodeId, label: val, group: type };
                                nodes.push(formattedData[nodeId]);
                            }
                            edges.push({ from: sourceUrl, to: nodeId });
                        });
                    }
                }
            }
        });
    }

    const container = document.getElementById('network');
    const graphData = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
    const options = {
        nodes: { shape: 'dot', size: 16 },
        physics: { stabilization: false }
    };
    new vis.Network(container, graphData, options);
}