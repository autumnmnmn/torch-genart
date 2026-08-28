
struct Uniforms /* buffer 0 0 */ {
    negative_scale: f32, // hard 0 to 10 = 1
    positive_scale: f32, // hard 0 to 10 = 1
    offset: f32, // -5 to 5 = 0
    nan_color: vec3f, // $color(var(--main-background))
    pos_color: vec3f, // $color
    neg_color: vec3f // $color
}

@group(0) @binding(0) var<uniform> uniforms: Uniforms;

@group(0) @binding(1) var tex: texture_2d<f32>;

$paste(core.wgsl);

@vertex
fn vert(@builtin(vertex_index) vertex_index: u32) -> @builtin(position) vec4<f32> {
    // fullscreen quad
    let pos = array<vec2<f32>, 6>(
        vec2<f32>(-1.0, -1.0), vec2<f32>(1.0, -1.0), vec2<f32>(-1.0, 1.0),
        vec2<f32>(1.0, -1.0), vec2<f32>(1.0, 1.0), vec2<f32>(-1.0, 1.0)
    );
    return vec4<f32>(pos[vertex_index], 0.0, 1.0);
}

@fragment
fn frag(@builtin(position) frag_coord: vec4<f32>) -> @location(0) vec4<f32> {
    let texel_coord = vec2<i32>(frag_coord.xy);

    var val = textureLoad(tex, texel_coord, 0) + uniforms.offset;

    let isnan = hacky_isinf(val.r);
    let div = val.g;
    //val.g = select(0.0, 1.0 - exp(val.r * uniforms.negative_scale), val.r < 0.0);
    //val.b = select(0.0, val.r * uniforms.positive_scale, val.r > 0.0);
    //val.r = max(val.g, val.b);
    let val3 = select((1.0 - exp(val.r * uniforms.negative_scale)) * uniforms.neg_color, val.r * uniforms.positive_scale * uniforms.pos_color, val.r > 0.0);

    val = vec4<f32>(val3, 1.0);
    //val.a = 1.0;

    return select(val, vec4<f32>(uniforms.nan_color, 1.0), isnan);
}

