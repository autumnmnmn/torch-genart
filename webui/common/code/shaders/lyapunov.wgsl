
struct Uniforms /* buffer 0 0 */ {
    width: u32,
    height: u32,
    center_low: vec2f,
    center_high: vec2f,
    zoom: f32,
    x_0: f32, // 0 to 1 = 0.5
    iterations: u32, // hard 0 to 500 = 100
    skip: u32, // hard 0 to 500 = 50
    seq_mask: u32, // hard 0 to hard 4294967295 = 5
    seq_len: u32, // hard 1 to hard 32 = 2
    seq_offset: u32, // hard 0 to hard 31 = 0
    mode: u32, // hard 0 to hard 3 = 0
    do_discont: u32, // hard 0 to hard 1 = 0 $bool $test
    discont_alpha: f32, // 0 to 1 = 0.907 $depend(do_discont)
    do_tent: u32, // hard 0 to hard 1 = 0 $bool
    do_neg: u32, // hard 0 to hard 1 = 0 $bool
    do_stochasticity: u32, // hard 0 to 1 = 0 $bool
    stochastic_modulus: u32, // 1 to 200 = 100 $depend(do_stochasticity)
    rotation: f32, // 0 to 1 = 0
}

@group(0) @binding(0) var<uniform> uniforms: Uniforms;
@group(0) @binding(1) var output_texture: texture_storage_2d<rg32float, write>;

$paste(core.wgsl);
$paste(complex.wgsl);
$paste(rng.wgsl);

@compute @workgroup_size(16, 16)
fn main(@builtin(global_invocation_id) id: vec3<u32>) {
    let px = id.x;
    let py = id.y;

    if (px >= uniforms.width || py >= uniforms.height) {
        return;
    }

    var r_vals = ${pixel_mapping}(id.xy, uniforms.center_low, uniforms.center_high, vec2u(uniforms.width, uniforms.height), uniforms.rotation, uniforms.zoom);

    var theta = uniforms.rotation * 3.14159265 * 2.0;
    var c = cos(theta);
    var s = sin(theta);
    //r_vals = mat2x2f(c,s,-s,c) * r_vals;

    var x: array<f32, 32>;
    for (var i = 0u; i < 32u; i++) {
        x[i] = uniforms.x_0;
    }

    var lyapunov: array<f32, 32> = array<f32, 32>();

    var flipped: bool = false;

    var diverged_at: u32 = 0;

    for (var iter = 0u; iter < uniforms.iterations; iter = iter + 1u) {
        var final_offset = select(uniforms.seq_len,0,uniforms.mode == 0u);
        for (var offset = 0u; offset <= final_offset; offset = offset + 1u) {
            let rng_seed = pcg_hash(px + pcg_hash(py << 1)) ^ pcg_hash(iter) ^ pcg_hash(bitcast<u32>(r_vals.x) + pcg_hash(bitcast<u32>(r_vals.y) << 1));
            // todo nan and inf checks
            var cond = ((uniforms.seq_mask >> ((iter + offset + uniforms.seq_offset) % uniforms.seq_len)) & 1u) != 0u;
            if (uniforms.do_stochasticity == 1) {
                flipped = select(flipped, !flipped, rng_seed % uniforms.stochastic_modulus == 0);
            }
            if (flipped) {
                cond = !cond;
            }

            var r = select(r_vals.x, r_vals.y, cond);
            var x_next = r * x[offset] * (1.0 - x[offset]);
            if (uniforms.do_tent == 1) {
                x_next = r * min(x[offset], 1.0 - x[offset]);
            }
            if (uniforms.do_neg == 1) {
                x_next = 1.0 - x_next;
            }
            if (uniforms.do_discont == 1 && x[offset] <= 0.5) {
                x_next = x_next + (uniforms.discont_alpha - 1.0) * (r - 2.0) / 4.0;
            }
            var term = log(abs(r * (1.0 - 2.0 * x[offset])));
            if (iter > uniforms.skip) {
                lyapunov[offset] = c_avg(lyapunov[offset], term, iter - uniforms.skip);
            }
            x[offset] = x_next;

        }
        if (hacky_isnan(x[0]) && diverged_at == 0) {
            diverged_at = iter;
        }
    }

    var val: f32;

    if (uniforms.mode == 0) {
        val = lyapunov[0];
    } else if (uniforms.mode == 1) {
        val = lyapunov[0];
        for (var i = 1u; i < uniforms.seq_len; i++) {
            val = min(val, lyapunov[i]);
        }
    } else if (uniforms.mode == 2) {
        val = lyapunov[0];
        for (var i = 1u; i < uniforms.seq_len; i++) {
            val = max(val, lyapunov[i]);
        }
    } else if (uniforms.mode == 3) {
        val = lyapunov[0];
        for (var i = 1u; i < uniforms.seq_len; i++) {
            val = val + lyapunov[i];
        }
        val = val / f32(uniforms.seq_len);
    }

    /*
    var r = pow(val, uniforms.pow_r);
    var g = pow(-val, uniforms.pow_g);
    var b = pow(-tanh(val), uniforms.pow_b);

    var color: vec4<f32> = vec4<f32>(r, g, b, 1.0);


    color = select(color, vec4<f32>(uniforms.nan_color, 1.0), isnan);
    */

    textureStore(output_texture, vec2<i32>(i32(px), i32(py)), vec4f(val, (f32(diverged_at) / f32(uniforms.iterations)), 0.0, 0.0));
}



